import os
import re
import json
import io
import time
import threading
import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
from flask import Flask

# ---- CONFIG ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
OWNER_IDS = [1329161792936476683, 903569932791463946]
MODLOG_CHANNEL = 1430175693223890994

# ---- JSON FILES ----
DATA_FOLDER = "data"
os.makedirs(DATA_FOLDER, exist_ok=True)
BANNED_FILE = os.path.join(DATA_FOLDER, "banned_guilds.json")
REMOVED_LOG = os.path.join(DATA_FOLDER, "removed_guilds.json")
BANNED_USERS_FILE = os.path.join(DATA_FOLDER, "banned_users.json")
TEMP_BANS_FILE = os.path.join(DATA_FOLDER, "tempbans.json")

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

BANNED_GUILDS = load_json(BANNED_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
TEMP_BANS = load_json(TEMP_BANS_FILE, {})  # {user_id: unban_timestamp}

# ---- Flask keep-alive ----
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask running on port {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord bot setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def is_owner_id(uid: int):
    return uid in OWNER_IDS

async def is_owner(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS

def to_int(val):
    try:
        return int(val)
    except:
        return None

async def modlog_send(message: str):
    channel = client.get_channel(MODLOG_CHANNEL)
    if channel:
        embed = discord.Embed(description=message, color=discord.Color.orange(), timestamp=discord.utils.utcnow())
        await channel.send(embed=embed)

# ---- TEMPBAN CHECK TASK ----
@tasks.loop(seconds=60)
async def check_tempbans():
    now = int(time.time())
    removed = []
    for uid, ts in list(TEMP_BANS.items()):
        if now >= ts:
            removed.append(uid)
            TEMP_BANS.pop(uid)
            save_json(TEMP_BANS_FILE, TEMP_BANS)
            user = client.get_user(uid)
            if user:
                await modlog_send(f"✅ User **{user}** ({uid}) temporary ban expired.")
check_tempbans.start()

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
        found = re.findall(r"(https?://[^\s]+roblox\.com/[^\s]*)", post.get("body",""))
        for f in found:
            if f not in links:
                links.append(f)
    return links

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links")
async def links_command(interaction: discord.Interaction):
    uid = interaction.user.id
    if interaction.guild_id in BANNED_GUILDS or uid in BANNED_USERS or (uid in TEMP_BANS):
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="ℹ️ You are banned from using this bot.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return
    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️",
                          description="\n".join(links[:10]),
                          color=discord.Color.orange())
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- OWNER COMMANDS ----
def owner_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        return await is_owner(interaction)
    return app_commands.check(predicate)

@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Numeric guild ID")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid: 
        await interaction.response.send_message("Invalid guild ID.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild {gid}", ephemeral=True)
    await modlog_send(f"🛑 Guild `{gid}` banned by {interaction.user}.")

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Numeric guild ID")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("Guild not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Unbanned guild {gid}", ephemeral=True)
    await modlog_send(f"✅ Guild `{gid}` unbanned by {interaction.user}.")

@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban")
async def ban_user(interaction: discord.Interaction, user_id: str):
    uid = to_int(user_id)
    if not uid or uid in BANNED_USERS:
        await interaction.response.send_message("Invalid or already banned.", ephemeral=True)
        return
    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User {uid} banned.", ephemeral=True)
    await modlog_send(f"🛑 User `{uid}` banned by {interaction.user}.")

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    uid = to_int(user_id)
    if not uid or uid not in BANNED_USERS:
        await interaction.response.send_message("User not in banned list.", ephemeral=True)
        return
    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User {uid} unbanned.", ephemeral=True)
    await modlog_send(f"✅ User `{uid}` unbanned by {interaction.user}.")

@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID", duration="Duration in seconds")
async def tempban(interaction: discord.Interaction, user_id: str, duration: int):
    uid = to_int(user_id)
    if not uid or uid in TEMP_BANS:
        await interaction.response.send_message("Invalid or already tempbanned.", ephemeral=True)
        return
    unban_ts = int(time.time()) + duration
    TEMP_BANS[uid] = unban_ts
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"User {uid} temporarily banned for {duration} seconds.", ephemeral=True)
    await modlog_send(f"⏱️ User `{uid}` tempbanned by {interaction.user} until <t:{unban_ts}:R>.")

@tree.command(name="ban_invite", description="Ban a guild by invite code (owner-only)")
@owner_only()
@app_commands.describe(invite="Invite code or URL")
async def ban_invite(interaction: discord.Interaction, invite: str):
    code = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not code:
        await interaction.response.send_message("Invalid invite code.", ephemeral=True)
        return
    code = code.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message(f"Failed to resolve invite (HTTP {resp.status})", ephemeral=True)
                return
            data = await resp.json()
    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("Could not fetch guild from invite.", ephemeral=True)
        return
    gid = guild.get("id")
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild `{guild.get('name','Unknown')}` ({gid})", ephemeral=True)
    await modlog_send(f"🛑 Guild `{guild.get('name','Unknown')}` ({gid}) banned via invite by {interaction.user}.")

# ---- EVENTS ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Guilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run Flask in background ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Run Discord ----
client.run(TOKEN)
