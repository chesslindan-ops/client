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
OWNER_ID = 1329161792936476683  # your user ID

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
BANNED_GUILDS = load_json(BANNED_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
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
    return interaction.user.id == OWNER_ID

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
    if uid in BANNED_USERS or is_tempbanned(uid):
        await interaction.response.send_message(
            "Error ⚠️: User is banned from using this program ❌ | DM h.aze.l to appeal.",
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
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    if interaction.guild_id in BANNED_GUILDS:
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

    # build numbered markdown links and separate with one blank line
    pretty = []
    for i, l in enumerate(links[:10], start=1):
        pretty.append(f"[Click Here ({i})]({l})")
    message = "\n\n".join(pretty)

    if MAINTENANCE:
        embed = discord.Embed(
            title="⚠️ Maintenance Mode 🟠 | Latest SAB Scammer Links 🔗",
            description=f"⚠️ The bot is currently in maintenance mode and may experience issues.\n\n{message}",
            color=0xFFA500
        )
    else:
        embed = discord.Embed(
            title="⚠️ Latest SAB Scammer PS Links 🔗",
            description=message,
            color=0x00ffcc
        )
    embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Owner-only decorator ----
def owner_only():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)

@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
@owner_only()
@app_commands.describe(state="on/off")
async def maintenance_cmd(interaction: discord.Interaction, state: str):
    s = state.lower()
    if s not in ["on","off"]:
        await interaction.response.send_message("use: /maintenance on  |  /maintenance off", ephemeral=True)
        return

    newstate = (s=="on")
    save_maintenance(newstate)

    await interaction.response.send_message(f"maintenance set to **{s}**", ephemeral=True)

# ---- Ban/unban users ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban")
async def ban_user(interaction: discord.Interaction, user_id: str):
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
    await interaction.response.send_message(f"✅ User `{uid}` banned.", ephemeral=True)

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
    if uid in BANNED_USERS:
        BANNED_USERS.remove(uid)
        save_json(BANNED_USERS_FILE, BANNED_USERS)
        removed = True

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
    if uid in BANNED_USERS or is_tempbanned(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    expires_at = time.time() + duration_minutes * 60
    TEMP_BANS.append({"id": uid, "expires": expires_at})
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes.", ephemeral=True)

# ---- Ban/unban guilds ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` banned.", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("⚠️ Guild not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` unbanned.", ephemeral=True)

# ---- Ban by invite ----
@tree.command(name="ban_invite", description="Ban a guild by invite (owner-only)")
@owner_only()
@app_commands.describe(invite="Invite code or URL")
async def ban_invite(interaction: discord.Interaction, invite: str):
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
    if gid in BANNED_GUILDS:
        await interaction.response.send_message(f"⚠️ Guild **{name}** already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild **{name}** banned.", ephemeral=True)

# ---- List banned / removed ----
@tree.command(name="list_banned", description="List all banned guilds (owner-only)")
@owner_only()
async def list_banned(interaction: discord.Interaction):
    lines = []
    for i, gid in enumerate(BANNED_GUILDS, start=1):
        gobj = client.get_guild(gid)
        name = gobj.name if gobj else "Not in guild"
        lines.append(f"{i}. {name} | {gid}")
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
@tree.command(name="announce", description="Send a global announcement (owner-only)")
@owner_only()
@app_commands.describe(message="Message to announce globally (multi-line allowed)")
async def announce(interaction: discord.Interaction, message: str):
    embed = discord.Embed(
        title="Global Announcement From Developer",
        description=message,  # multi-line works here
        color=0x0000ff
    )
    sent_count = 0
    for guild in client.guilds:
        # try to send in the first text channel the bot can send messages in
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send(embed=embed)
                    sent_count += 1
                except:
                    pass
                break  # only send once per guild
    await interaction.response.send_message(f"✅ Announcement sent to {sent_count} guilds.", ephemeral=True)
# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced and ready!")
    print("Guilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")
    print("Currently banned guild ids:", BANNED_GUILDS)

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
