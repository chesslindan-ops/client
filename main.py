import os
import re
import threading
import json
import io
import time
import asyncio
import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
from flask import Flask

# ---- Config ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

OWNER_IDS = [1329161792936476683, 903569932791463946]
MODLOG_CHANNEL = 1430175693223890994

# ---- File storage ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"
MAINT_FILE = "maintenance.json"

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
TEMP_BANS = load_json(TEMP_BANS_FILE, {})  # user_id -> unix timestamp
MAINTENANCE = load_json(MAINT_FILE, {"enabled": False})

# ---- Flask keep-alive ----
app = Flask(__name__)
@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask).start()

# ---- Discord setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int(val):
    try: return int(val)
    except: return None

async def is_owner(interaction: discord.Interaction):
    return interaction.user.id in OWNER_IDS

async def modlog_send(embed: discord.Embed):
    channel = client.get_channel(MODLOG_CHANNEL)
    if channel:
        await channel.send(embed=embed)

# ---- Roblox fetch ----
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
    seen = set(); unique_links = []
    for l in links:
        if l not in seen: seen.add(l); unique_links.append(l)
    return unique_links

# ---- /links ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    uid = interaction.user.id
    gid = interaction.guild_id
    now = int(time.time())
    # maintenance mode
    if MAINTENANCE.get("enabled"):
        embed = discord.Embed(title="⚠️ Maintenance Mode Active", description="The bot may experience issues currently. Proceed with caution.", color=discord.Color.orange())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    # check bans
    if gid in BANNED_GUILDS:
        embed = discord.Embed(title="Access Denied ❌️", description="⚠️ This guild is banned from using this bot. Contact @h.aze.l to appeal.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if uid in BANNED_USERS:
        embed = discord.Embed(title="Access Denied ❌️", description="⚠️ You have been permanently banned from using this bot. Contact @h.aze.l to appeal.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if str(uid) in TEMP_BANS:
        exp = TEMP_BANS[str(uid)]
        if now < exp:
            embed = discord.Embed(title="Temporary Ban ⏱️", description=f"⚠️ You are temporarily banned from using this bot until <t:{exp}:R>. Contact @h.aze.l to appeal.", color=discord.Color.orange())
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            del TEMP_BANS[str(uid)]
            save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return
    message = "\n".join(links[:10])
    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️", description=message, color=0x00ffcc)
    embed.set_footer(text="DM @h.aze.l for bug reports.| Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Owner-only helper decorator ----
def owner_only(func):
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        if interaction.user.id not in OWNER_IDS:
            await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
            return
        return await func(interaction, *args, **kwargs)
    return wrapper

# ---- Ban / Unban / Tempban / Maintenance ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID")
@owner_only
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid: return await interaction.response.send_message("Invalid guild ID.", ephemeral=True)
    if gid in BANNED_GUILDS: return await interaction.response.send_message("Guild already banned.", ephemeral=True)
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await modlog_send(discord.Embed(title="Guild Banned ✅", description=f"Banned guild ID `{gid}`", color=discord.Color.red()))
    await interaction.response.send_message(f"Guild `{gid}` banned.", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID")
@owner_only
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid or gid not in BANNED_GUILDS: return await interaction.response.send_message("Guild not in banned list.", ephemeral=True)
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await modlog_send(discord.Embed(title="Guild Unbanned ✅", description=f"Unbanned guild ID `{gid}`", color=discord.Color.green()))
    await interaction.response.send_message(f"Guild `{gid}` unbanned.", ephemeral=True)

@tree.command(name="ban_user", description="Ban a user (owner-only)")
@app_commands.describe(user_id="Numeric user ID")
@owner_only
async def ban_user(interaction: discord.Interaction, user_id: str):
    uid = to_int(user_id)
    if not uid: return await interaction.response.send_message("Invalid user ID.", ephemeral=True)
    if uid in BANNED_USERS: return await interaction.response.send_message("User already banned.", ephemeral=True)
    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await modlog_send(discord.Embed(title="User Banned ✅", description=f"Banned user <@{uid}>", color=discord.Color.red()))
    await interaction.response.send_message(f"User <@{uid}> banned.", ephemeral=True)

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@app_commands.describe(user_id="Numeric user ID")
@owner_only
async def unban_user(interaction: discord.Interaction, user_id: str):
    uid = to_int(user_id)
    if not uid or uid not in BANNED_USERS: return await interaction.response.send_message("User not in banned list.", ephemeral=True)
    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await modlog_send(discord.Embed(title="User Unbanned ✅", description=f"Unbanned user <@{uid}>", color=discord.Color.green()))
    await interaction.response.send_message(f"User <@{uid}> unbanned.", ephemeral=True)

@tree.command(name="tempban", description="Temporarily ban a user in minutes (owner-only)")
@app_commands.describe(user_id="Numeric user ID", duration_min="Duration in minutes")
@owner_only
async def tempban(interaction: discord.Interaction, user_id: str, duration_min: int):
    uid = to_int(user_id)
    if not uid: return await interaction.response.send_message("Invalid user ID.", ephemeral=True)
    expire = int(time.time()) + max(1, duration_min * 60)
    TEMP_BANS[str(uid)] = expire
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await modlog_send(discord.Embed(title="Tempban ⏱️", description=f"Temporarily banned <@{uid}> for {duration_min} minute(s). Expires <t:{expire}:R>", color=discord.Color.orange()))
    await interaction.response.send_message(f"User <@{uid}> tempbanned for {duration_min} minute(s).", ephemeral=True)

@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
@owner_only
async def maintenance(interaction: discord.Interaction):
    MAINTENANCE["enabled"] = not MAINTENANCE.get("enabled", False)
    save_json(MAINT_FILE, MAINTENANCE)
    status = "enabled" if MAINTENANCE["enabled"] else "disabled"
    color = discord.Color.orange() if MAINTENANCE["enabled"] else discord.Color.green()
    await modlog_send(discord.Embed(title="Maintenance Mode", description=f"Maintenance mode {status}", color=color))
    await interaction.response.send_message(f"Maintenance mode {status}.", ephemeral=True)

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"Logged in as {client.user} — {len(client.guilds)} guilds")
    # clean expired tempbans
    now = int(time.time())
    expired = [uid for uid, ts in TEMP_BANS.items() if ts < now]
    for uid in expired: del TEMP_BANS[uid]
    save_json(TEMP_BANS_FILE, TEMP_BANS)

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run Discord ----
client.run(TOKEN)
