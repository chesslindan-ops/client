import os
import re
import threading
import json
import time
import aiohttp
import discord
from discord import app_commands
from flask import Flask

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- File storage ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
MAINT_FILE = "maintenance.json"
TEMP_BANS_FILE = "tempbans.json"

# ---- Load JSON ----
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {path}: {e}")

# ---- Data ----
BANNED_GUILDS = load_json(BANNED_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
TEMP_BANS = load_json(TEMP_BANS_FILE, [])
MAINTENANCE = load_json(MAINT_FILE, {}).get("enabled", False)

def save_maintenance(state: bool):
    global MAINTENANCE
    MAINTENANCE = state
    save_json(MAINT_FILE, {"enabled": state})

# ---- Owner ID ----
OWNER_IDS = [1329161792936476683, 903569932791463946]

# ---- Flask ----
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask running on port {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int_gid(val):
    try:
        return int(val)
    except:
        return None

def is_tempbanned(user_id: int) -> bool:
    now = time.time()
    global TEMP_BANS
    updated = [b for b in TEMP_BANS if b["expires_at"] > now]
    if len(updated) != len(TEMP_BANS):
        TEMP_BANS = updated
        save_json(TEMP_BANS_FILE, TEMP_BANS)
    return any(b["user_id"] == user_id for b in TEMP_BANS)

async def check_user_ban(interaction: discord.Interaction):
    if interaction.user.id in BANNED_USERS:
        await interaction.response.send_message(
            "Error ⚠️: User is banned from using this program ❌ | DM h.aze.l to appeal.",
            ephemeral=True
        )
        return True
    if is_tempbanned(interaction.user.id):
        await interaction.response.send_message(
            "⚠️ You are temporarily banned from using this bot. ⏳",
            ephemeral=True
        )
        return True
    return False

# ---- Fetch Roblox group posts ----
async def fetch_group_posts():
    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"} if ROBLOX_COOKIE else {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200:
                print(f"⚠️ Failed to fetch posts: {resp.status}")
                return []
            data = await resp.json()

    links = []
    for post in data.get("data", []):
        content = post.get("body", "")
        found = re.findall(r"(https?://[^\s]+roblox\.com/[^\s]*)", content)
        links.extend(found)

    seen = set()
    unique_links = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique_links.append(l)
    return unique_links

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    if await check_user_ban(interaction):
        return

    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied ❌ | Error JS0007",
            description="⚠️ This guild is banned from using this bot. Contact @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return

    message = "\n".join(links[:10])
    if MAINTENANCE:
        embed = discord.Embed(
            title="⚠️ Maintenance Mode Active 🟠 | Latest SAB Scammer Links 🔗",
            description=f"⚠️ The bot is currently in maintenance mode and may experience issues.\n\n{message}",
            color=0xFFA500
        )
    else:
        embed = discord.Embed(
            title="Latest SAB Scammer Links 🔗⚠️",
            description=message,
            color=0x0000ff
        )
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS in collaboration with **Quesadillo's Mansion**")
    await interaction.followup.send(embed=embed)

# ---- Owner-only commands ----
@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
async def maintenance(interaction: discord.Interaction, enable: bool):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    save_maintenance(enable)
    state_text = "ENABLED 🟠" if enable else "DISABLED ✅"
    await interaction.response.send_message(f"Maintenance mode {state_text}", ephemeral=True)

# ---- User bans ----
@tree.command(name="ban_user", description="Owner-only")
async def ban_user(interaction: discord.Interaction, user_id: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if uid in BANNED_USERS:
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` has been banned.", ephemeral=True)

@tree.command(name="unban_user", description="Owner-only")
async def unban_user(interaction: discord.Interaction, user_id: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if uid not in BANNED_USERS:
        await interaction.response.send_message("⚠️ User not in banned list.", ephemeral=True)
        return
    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` has been unbanned.", ephemeral=True)

# ---- Tempban/untempban ----
@tree.command(name="tempban_user", description="Owner-only, temp ban user (minutes)")
async def tempban_user(interaction: discord.Interaction, user_id: str, minutes: int):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    expires_at = time.time() + (minutes * 60)
    TEMP_BANS.append({"user_id": uid, "expires_at": expires_at})
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"✅ User `{uid}` has been temporarily banned for {minutes} minutes.", ephemeral=True)

@tree.command(name="untempban_user", description="Owner-only, remove tempban")
async def untempban_user(interaction: discord.Interaction, user_id: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    global TEMP_BANS
    TEMP_BANS = [b for b in TEMP_BANS if b["user_id"] != uid]
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"✅ User `{uid}` is no longer temporarily banned.", ephemeral=True)

# ---- Guild bans ----
@tree.command(name="ban_guild", description="Owner-only")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` has been banned.", ephemeral=True)

@tree.command(name="unban_guild", description="Owner-only")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.followup.send("❌ Invalid guild ID.", ephemeral=True)
        return
    if gid not in BANNED_GUILDS:
        await interaction.followup.send("⚠️ Guild not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.followup.send(f"✅ Guild `{gid}` has been unbanned.", ephemeral=True)

# ---- Ban via invite (fixed) ----
@tree.command(name="ban_invite", description="Owner-only")
async def ban_invite(interaction: discord.Interaction, invite: str):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    invite = invite.strip().rstrip("/")
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)", invite)
    if not m:
        await interaction.followup.send("❌ Could not parse invite.", ephemeral=True)
        return

    code = m.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.followup.send(f"❌ Failed to resolve invite (HTTP {resp.status}).", ephemeral=True)
                return
            data = await resp.json()

    guild_data = data.get("guild")
    if not guild_data:
        await interaction.followup.send("❌ Invite resolved but no guild info.", ephemeral=True)
        return

    try:
        gid_int = int(guild_data["id"])
    except:
        await interaction.followup.send("❌ Could not parse guild ID from invite.", ephemeral=True)
        return

    if gid_int in BANNED_GUILDS:
        await interaction.followup.send(f"⚠️ Guild **{guild_data.get('name','Unknown')}** (`{gid_int}`) is already banned.", ephemeral=True)
        return

    BANNED_GUILDS.append(gid_int)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.followup.send(f"✅ Guild **{guild_data.get('name','Unknown')}** (`{gid_int}`) has been banned.", ephemeral=True)

# ---- List banned/removed ----
@tree.command(name="list_banned", description="Owner-only")
async def list_banned(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    if not BANNED_GUILDS:
        await interaction.response.send_message("No banned guilds.", ephemeral=True)
        return
    text = "\n".join([str(gid) for gid in BANNED_GUILDS])
    await interaction.response.send_message(f"**Banned guilds:**\n{text}", ephemeral=True)

@tree.command(name="list_removed", description="Owner-only")
async def list_removed(interaction: discord.Interaction):
    if interaction.user.id not in OWNER_IDS:
        await interaction.response.send_message("❌ You cannot use this command.", ephemeral=True)
        return
    if not REMOVED_GUILDS:
        await interaction.response.send_message("No recorded removed guilds.", ephemeral=True)
        return
    text = "\n".join([f"{x['name']} | {x['id']}" for x in REMOVED_GUILDS])
    await interaction.response.send_message(f"**Removed guilds:**\n{text}", ephemeral=True)

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced.")
    print("\nGuilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")
    print("_________________________")
    print(f"Banned guilds: {BANNED_GUILDS}")
    print(f"Banned users: {BANNED_USERS}")
    print(f"Maintenance mode: {'ON 🟠' if MAINTENANCE else 'OFF ✅'}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run Flask + Discord ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

client.run(TOKEN)
