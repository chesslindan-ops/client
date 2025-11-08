import os
import re
import threading
import json
import io
import time
import discord
from discord import app_commands
from flask import Flask
import aiohttp

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- Owners ----
OWNER_IDS = [
    1329161792936476683,  # you
    # add more owner IDs here
]

# ---- JSON files ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving {path}: {e}")

# ---- Load data ----
BANNED_GUILDS = load_json(BANNED_FILE, [])  # dicts with {"id": ..., "reason": ...}
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])  # dicts with {"id": ..., "reason": ...}
TEMP_BANS = load_json(TEMP_BANS_FILE, [])

def save_tempbans():
    save_json(TEMP_BANS_FILE, TEMP_BANS)

# ---- Flask keepalive ----
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask running on port {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int_gid(val):
    try:
        return int(val)
    except:
        return None

async def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS

def is_tempbanned(user_id: int):
    now = time.time()
    for entry in TEMP_BANS[:]:
        if entry["expires"] <= now:
            TEMP_BANS.remove(entry)
            save_tempbans()
        elif entry["id"] == user_id:
            return True
    return False

async def check_user_ban(interaction: discord.Interaction):
    uid = interaction.user.id
    for entry in BANNED_USERS:
        if entry["id"] == uid:
            await interaction.response.send_message(
                f"Error ⚠️: User is banned from using this program ❌\nReason: {entry.get('reason','No reason')}\nDM h.aze.l to appeal.",
                ephemeral=True
            )
            return True
    if is_tempbanned(uid):
        await interaction.response.send_message(
            "Error ⚠️: User is temporarily banned from using this program ❌ | DM h.aze.l to appeal.",
            ephemeral=True
        )
        return True
    return False

# ---- Fetch group posts ----
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
    # dedupe
    seen = set()
    unique_links = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique_links.append(l)
    return unique_links

# ---- Maintenance flag ----
MAINTENANCE = False
def save_maintenance(state: bool):
    global MAINTENANCE
    MAINTENANCE = state

# ---- /links command ----
@tree.command(name="link", description="Get a scammer private server link! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    if any(g["id"] == interaction.guild_id for g in BANNED_GUILDS):
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="This server is blacklisted from using this bot. Contact @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    if await check_user_ban(interaction):
        return

    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return

    # only send first link, as clickable markdown
    link_message = f"[Scammer Private Server Link (Click here!)]({links[0]})"

    if MAINTENANCE:
        embed = discord.Embed(
            title="⚠️ Maintenance Mode 🟠 | Latest SAB Scammer Link 🔗",
            description=f"⚠️ The bot is currently in maintenance mode and may experience issues.\n\n{link_message}",
            color=0xFFA500
        )
    else:
        embed = discord.Embed(
            title="🔍・𝗥𝗲𝗰𝗲𝗻𝘁 𝗗𝗲𝘁𝗲𝗰𝘁𝗲𝗱 𝗦𝗰𝗮𝗺𝗺𝗲𝗿 🔗",
            description=link_message,
            color=0x0000ff
        )
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS | Hosted by Quesadillo's Mansion")
    embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
    await interaction.followup.send(embed=embed)

# ---- Owner-only decorator ----
def owner_only():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id in OWNER_IDS
    return app_commands.check(predicate)

# ---- Ban/unban users ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban", reason="Reason for ban")
async def ban_user(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    for entry in BANNED_USERS:
        if entry["id"] == uid:
            await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
            return
    BANNED_USERS.append({"id": uid, "reason": reason})
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` banned for reason: {reason}", ephemeral=True)

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    removed = False
    for entry in BANNED_USERS[:]:
        if entry["id"] == uid:
            BANNED_USERS.remove(entry)
            removed = True
    save_json(BANNED_USERS_FILE, BANNED_USERS)

    for entry in TEMP_BANS[:]:
        if entry["id"] == uid:
            TEMP_BANS.remove(entry)
            removed = True
    save_tempbans()

    if removed:
        await interaction.response.send_message(f"✅ User `{uid}` has been unbanned.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ User was not banned.", ephemeral=True)

# ---- Tempban ----
@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to tempban", duration_minutes="Duration in minutes")
async def tempban(interaction: discord.Interaction, user_id: str, duration_minutes: int):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if any(entry["id"] == uid for entry in BANNED_USERS) or is_tempbanned(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    expires_at = time.time() + duration_minutes * 60
    TEMP_BANS.append({"id": uid, "expires": expires_at})
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes.", ephemeral=True)

# ---- Ban/unban guilds ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to ban", reason="Reason for ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str, reason: str = "No reason provided"):
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if any(g["id"] == gid for g in BANNED_GUILDS):
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append({"id": gid, "reason": reason})
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` banned for reason: {reason}", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid or not any(g["id"] == gid for g in BANNED_GUILDS):
        await interaction.response.send_message("⚠️ Guild not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS[:] = [g for g in BANNED_GUILDS if g["id"] != gid]
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` unbanned.", ephemeral=True)

# ---- Ban by invite ----
@tree.command(name="ban_invite", description="Ban a guild by invite (owner-only)")
@owner_only()
@app_commands.describe(invite="Invite code or URL", reason="Reason for ban")
async def ban_invite(interaction: discord.Interaction, invite: str, reason: str = "No reason provided"):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("❌ Could not parse invite.", ephemeral=True)
        return
    code = m.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message(f"❌ Failed to resolve invite (HTTP {resp.status}).", ephemeral=True)
                return
            data = await resp.json()
    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("❌ Invite has no guild info.", ephemeral=True)
        return
    gid = int(guild["id"])
    name = guild.get("name", "Unknown")
    if any(g["id"] == gid for g in BANNED_GUILDS):
        await interaction.response.send_message(f"⚠️ Guild **{name}** already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append({"id": gid, "reason": reason})
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild **{name}** banned for reason: {reason}", ephemeral=True)

# ---- List banned / removed ----
@tree.command(name="list_banned", description="List all banned guilds (owner-only)")
@owner_only()
async def list_banned(interaction: discord.Interaction):
    lines = []
    for i, g in enumerate(BANNED_GUILDS, start=1):
        gobj = client.get_guild(g["id"])
        name = gobj.name if gobj else "Not in guild"
        lines.append(f"{i}. {name} | {g['id']} | Reason: {g.get('reason','No reason')}")
    text = "\n".join(lines) or "No banned guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Banned guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "banned_guilds.txt"), ephemeral=True)

@tree.command(name="list_removed", description="List removed guilds (owner-only)")
@owner_only()
async def list_removed(interaction: discord.Interaction):
    lines = [f"{i+1}. {e.get('name','Unknown')} | {e.get('id','Unknown')}" for i, e in enumerate(REMOVED_GUILDS)]
    text = "\n".join(lines) or "No removed guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Removed guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "removed_guilds.txt"), ephemeral=True)

# ---- Manage owners commands ----
@tree.command(name="list_owners", description="List all bot owners (owner-only)")
@owner_only()
async def list_owners(interaction: discord.Interaction):
    lines = [f"{i+1}. <@{uid}> | {uid}" for i, uid in enumerate(OWNER_IDS)]
    text = "\n".join(lines) or "No owners set."
    await interaction.response.send_message(f"**Bot Owners:**\n{text}", ephemeral=True)

@tree.command(name="add_owner", description="Add a new bot owner (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to add as owner")
async def add_owner(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if uid in OWNER_IDS:
        await interaction.response.send_message("⚠️ User is already an owner.", ephemeral=True)
        return
    OWNER_IDS.append(uid)
    await interaction.response.send_message(f"✅ <@{uid}> added as owner.", ephemeral=True)

@tree.command(name="remove_owner", description="Remove a bot owner (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to remove from owners")
async def remove_owner(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if uid not in OWNER_IDS:
        await interaction.response.send_message("⚠️ User is not an owner.", ephemeral=True)
        return
    OWNER_IDS.remove(uid)
    await interaction.response.send_message(f"✅ <@{uid}> removed from owners.", ephemeral=True)

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced and ready!")
    print("Guilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")
    print("Currently banned guild ids:", [g["id"] for g in BANNED_GUILDS])

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run Flask ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Run Discord ----
client.run(TOKEN)
