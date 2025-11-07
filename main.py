import os
import re
import threading
import json
import io
import asyncio
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
from flask import Flask

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- Multi-owner IDs ----
OWNER_IDS = [1329161792936476683, 903569932791463946]

# ---- Modlog channel ID ----
MODLOG_CHANNEL_ID = 1430175693223890994

# ---- File storage ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"

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
TEMP_BANS = load_json(TEMP_BANS_FILE, {})

# ---- Flask setup ----
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask running on port {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord bot ----
intents = discord.Intents.default()
intents.guilds = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int(val):
    try:
        return int(val)
    except Exception:
        return None

async def is_owner(interaction: discord.Interaction):
    return interaction.user.id in OWNER_IDS

async def log_mod_action(message: str):
    channel = client.get_channel(MODLOG_CHANNEL_ID)
    if not channel:
        return
    embed = discord.Embed(description=message, color=0xFFA500, timestamp=datetime.utcnow())
    await channel.send(embed=embed)

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
@tree.command(name="links", description="Get scammer private server links!")
async def links_command(interaction: discord.Interaction):
    # Guild ban
    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="ℹ️ This bot is no longer associated with this server.\nDM @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # User ban
    if interaction.user.id in BANNED_USERS:
        embed = discord.Embed(
            title="Error ⚠️",
            description="You are banned from using this bot ❌️\nDM @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Maintenance mode
    if TEMP_BANS.get("maintenance", False):
        embed = discord.Embed(
            title="⚠️ Maintenance Mode",
            description="⚠️ The bot might experience issues. Proceed with caution.\nLinks below may be delayed.",
            color=0xFFA500
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return

    message = "\n".join(links[:10])
    embed = discord.Embed(
        title="Latest SAB Scammer Links 🔗⚠️",
        description=message,
        color=0x00ffcc
    )
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)


# ---- Owner-only checks ----
def owner_only(func):
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if not await is_owner(interaction):
            await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
            return
        await func(interaction, *args, **kwargs)
    return wrapper


# ---- Ban / Unban guild ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID to ban")
@owner_only
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("Invalid guild id.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("That guild is already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild `{gid}`.", ephemeral=True)
    await log_mod_action(f"✅ Guild `{gid}` banned by {interaction.user}.")


@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID to unban")
@owner_only
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("Guild id not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Unbanned guild `{gid}`.", ephemeral=True)
    await log_mod_action(f"✅ Guild `{gid}` unbanned by {interaction.user}.")


# ---- Ban / Unban user ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@app_commands.describe(user="User ID to ban")
@owner_only
async def ban_user(interaction: discord.Interaction, user: str):
    uid = to_int(user)
    if not uid:
        await interaction.response.send_message("Invalid user id.", ephemeral=True)
        return
    if uid in BANNED_USERS:
        await interaction.response.send_message("User is already banned.", ephemeral=True)
        return
    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"Banned user `{uid}`.", ephemeral=True)
    await log_mod_action(f"✅ User `{uid}` banned by {interaction.user}.")


@tree.command(name="unban_user", description="Unban a user (owner-only)")
@app_commands.describe(user="User ID to unban")
@owner_only
async def unban_user(interaction: discord.Interaction, user: str):
    uid = to_int(user)
    if not uid or uid not in BANNED_USERS:
        await interaction.response.send_message("User id not in banned list.", ephemeral=True)
        return
    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"Unbanned user `{uid}`.", ephemeral=True)
    await log_mod_action(f"✅ User `{uid}` unbanned by {interaction.user}.")


# ---- Tempban ----
@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@app_commands.describe(user="User ID to tempban", duration_minutes="Duration in minutes")
@owner_only
async def tempban(interaction: discord.Interaction, user: str, duration_minutes: int):
    uid = to_int(user)
    if not uid:
        await interaction.response.send_message("Invalid user id.", ephemeral=True)
        return
    expire = datetime.utcnow() + timedelta(minutes=duration_minutes)
    TEMP_BANS[str(uid)] = expire.isoformat()
    save_json(TEMP_BANS_FILE, TEMP_BANS)

    if uid not in BANNED_USERS:
        BANNED_USERS.append(uid)
        save_json(BANNED_USERS_FILE, BANNED_USERS)

    await interaction.response.send_message(f"Temporarily banned `{uid}` for {duration_minutes} minutes.", ephemeral=True)
    await log_mod_action(f"⏱️ User `{uid}` tempbanned for {duration_minutes} minutes by {interaction.user}.")


# ---- Auto-unban task ----
@tasks.loop(seconds=30)
async def check_tempbans():
    now = datetime.utcnow()
    removed = []
    for uid, expire_iso in list(TEMP_BANS.items()):
        expire = datetime.fromisoformat(expire_iso)
        if now >= expire:
            uid_int = int(uid)
            if uid_int in BANNED_USERS:
                BANNED_USERS.remove(uid_int)
                save_json(BANNED_USERS_FILE, BANNED_USERS)
            removed.append(uid)
            await log_mod_action(f"⏰ Tempban expired: User `{uid}` unbanned automatically.")
    for uid in removed:
        TEMP_BANS.pop(uid)
        save_json(TEMP_BANS_FILE, TEMP_BANS)


# ---- Preserve /ban_invite (as-is) ----
@tree.command(name="ban_invite", description="Ban a guild using an invite (owner-only)")
@app_commands.describe(invite="Invite code or URL")
@owner_only
async def ban_invite(interaction: discord.Interaction, invite: str):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("Invalid invite.", ephemeral=True)
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
    await interaction.response.send_message(f"Banned guild **{guild.get('name')}** (`{gid}`).", ephemeral=True)
    await log_mod_action(f"✅ Guild `{gid}` banned via invite by {interaction.user}.")


# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    check_tempbans.start()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced.")


@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")


@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)


# ---- Run Flask thread ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Run bot ----
client.run(TOKEN)
