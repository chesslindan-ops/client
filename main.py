import os
import re
import json
import io
import threading
import datetime
import discord
from discord import app_commands
import aiohttp
from flask import Flask

# ---- Secrets & Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
MODLOG_CHANNEL = 1430175693223890994
OWNER_IDS = [1329161792936476683, 903569932791463946]

# ---- JSON storage ----
BANNED_FILE = "banned_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"
REMOVED_LOG = "removed_guilds.json"

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
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
TEMP_BANS = load_json(TEMP_BANS_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])

# ---- Flask keep-alive ----
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask keep-alive running on {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord setup ----
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helper functions ----
def to_int_gid(val):
    try:
        return int(val)
    except:
        return None

async def is_owner_check(interaction: discord.Interaction) -> bool:
    return interaction.user.id in OWNER_IDS

async def log_mod_action(message: str):
    channel = client.get_channel(MODLOG_CHANNEL)
    if channel:
        timestamp = discord.utils.format_dt(datetime.datetime.now(), style='f')
        embed = discord.Embed(description=message, color=0xffa500, timestamp=datetime.datetime.utcnow())
        embed.set_footer(text=f"ModLog • {timestamp}")
        await channel.send(embed=embed)

# ---- Roblox group posts fetch ----
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
        found = re.findall(r"(https?://[^\s]+roblox\.com/[^\s]*)", post.get("body", ""))
        links.extend(found)
    seen = set()
    return [l for l in links if not (l in seen or seen.add(l))]

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(title="Access Denied ❌️ JS0007",
                              description="⚠️ This guild is blacklisted from using this bot. Please contact @h.aze.l to appeal.",
                              color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.user.id in BANNED_USERS:
        embed = discord.Embed(title="Access Denied ❌️",
                              description="❌️ You are permanently banned from using this bot. Contact @h.aze.l to appeal.",
                              color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # check tempbans
    now_ts = int(datetime.datetime.utcnow().timestamp())
    for ban in TEMP_BANS[:]:
        if now_ts >= ban.get("unban_ts", 0):
            TEMP_BANS.remove(ban)
            save_json(TEMP_BANS_FILE, TEMP_BANS)
            await log_mod_action(f"⏱️ Tempban expired: {ban['user_id']}")

    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return
    message = "\n".join(links[:10])
    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️", description=message, color=0xFFA500)
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Start Flask thread ----
threading.Thread(target=run_flask).start()
# ---- Owner-only commands: Guild & User bans ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(guild_id="Numeric guild ID to ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("Invalid guild ID. Use numeric format.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("This guild is already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Banned guild ID `{gid}`.", ephemeral=True)
    await log_mod_action(f"🛑 Guild banned: {gid} by {interaction.user} ({interaction.user.id})")

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(guild_id="Numeric guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("Guild ID is not banned.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Unbanned guild ID `{gid}`.", ephemeral=True)
    await log_mod_action(f"✅ Guild unbanned: {gid} by {interaction.user} ({interaction.user.id})")

@tree.command(name="ban_user", description="Ban a user from using the bot (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(user_id="User ID to ban")
async def ban_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        return
    if uid in BANNED_USERS:
        await interaction.response.send_message("User is already banned.", ephemeral=True)
        return
    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` banned.", ephemeral=True)
    await log_mod_action(f"🛑 User banned: {uid} by {interaction.user} ({interaction.user.id})")

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(user_id="User ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        return
    if uid not in BANNED_USERS:
        await interaction.response.send_message("User is not banned.", ephemeral=True)
        return
    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` unbanned.", ephemeral=True)
    await log_mod_action(f"✅ User unbanned: {uid} by {interaction.user} ({interaction.user.id})")

# ---- Temporary ban ----
@tree.command(name="tempban", description="Temporarily ban a user for X seconds (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(user_id="User ID", duration="Duration in seconds")
async def tempban(interaction: discord.Interaction, user_id: str, duration: int):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        return
    now_ts = int(datetime.datetime.utcnow().timestamp())
    unban_ts = now_ts + duration
    TEMP_BANS.append({"user_id": uid, "unban_ts": unban_ts})
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"⏱️ User `{uid}` temporarily banned for {duration} seconds.", ephemeral=True)
    await log_mod_action(f"⏱️ Tempban: {uid} for {duration}s by {interaction.user} ({interaction.user.id})")

# ---- Ban using invite (resolve guild) ----
@tree.command(name="ban_invite", description="Ban a guild by invite link (owner-only)")
@app_commands.check(is_owner_check)
@app_commands.describe(invite="Discord invite code or URL")
async def ban_invite(interaction: discord.Interaction, invite: str):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("Could not parse invite.", ephemeral=True)
        return
    code = m.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                await interaction.response.send_message(f"Failed to resolve invite (HTTP {resp.status}).", ephemeral=True)
                return
            data = await resp.json()
    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("Invite resolved but no guild info.", ephemeral=True)
        return
    gid = int(guild.get("id"))
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Banned guild **{guild.get('name')}** (`{gid}`).", ephemeral=True)
    await log_mod_action(f"🛑 Guild banned via invite: {guild.get('name')} ({gid}) by {interaction.user} ({interaction.user.id})")

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced and ready!")
    print("\nGuilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")
    print("_________________________")
    print(f"Currently banned guilds: {BANNED_GUILDS}")
    print(f"Currently banned users: {BANNED_USERS}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)
    await log_mod_action(f"❌ Removed from guild: {guild.name} ({guild.id})")

# ---- Run Discord ----
client.run(TOKEN)
