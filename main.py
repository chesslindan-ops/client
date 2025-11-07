import os
import re
import threading
import json
import io
import discord
from discord import app_commands
import aiohttp
from flask import Flask
from datetime import datetime, timedelta
import asyncio

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
OWNER_IDS = [1329161792936476683, 903569932791463946]  # Owner IDs
MODLOG_CHANNEL = 1430175693223890994  # Modlog channel ID

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
    except:
        return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

BANNED_GUILDS = load_json(BANNED_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
TEMP_BANS = load_json(TEMP_BANS_FILE, {})
MAINTENANCE = load_json(MAINT_FILE, {"enabled": False})

# ---- Flask setup ----
app = Flask(__name__)
@app.route('/')
def home(): return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

flask_thread = threading.Thread(target=run_flask, daemon=True)
flask_thread.start()

# ---- Discord bot setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int(val):
    try: return int(val)
    except: return None

async def is_owner(user_id: int):
    return user_id in OWNER_IDS

async def log_mod(action: str):
    channel = client.get_channel(MODLOG_CHANNEL)
    if channel:
        embed = discord.Embed(title="Mod Action", description=action, color=discord.Color.orange())
        embed.timestamp = datetime.utcnow()
        await channel.send(embed=embed)

# ---- Roblox fetch ----
async def fetch_group_posts():
    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"} if ROBLOX_COOKIE else {}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status != 200: return []
            data = await resp.json()
    links, seen = [], set()
    for post in data.get("data", []):
        content = post.get("body", "")
        found = re.findall(r"(https?://[^\s]+roblox\.com/[^\s]*)", content)
        for l in found:
            if l not in seen:
                seen.add(l)
                links.append(l)
    return links

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="ℹ️ This bot is no longer associated with this server | Contact @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if interaction.user.id in BANNED_USERS:
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="ℹ️ You are banned from using this bot | Contact @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    if TEMP_BANS.get(str(interaction.user.id)):
        ts = TEMP_BANS[str(interaction.user.id)]
        embed = discord.Embed(
            title="Temporary Ban ❌️",
            description=f"ℹ️ You are temporarily banned until <t:{ts}:R>",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    if MAINTENANCE.get("enabled"):
        embed = discord.Embed(
            title="⚠️ Maintenance Mode",
            description="ℹ️ Bot is under maintenance. Some features may be unstable.",
            color=discord.Color.orange()
        )
        await interaction.followup.send(embed=embed)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return
    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️", description="\n".join(links[:10]), color=0x00ffcc)
    embed.set_footer(text="DM @h.aze.l for bug reports.| Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Admin Commands ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
        return
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("✅ Guild already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Banned guild `{gid}`.", ephemeral=True)
    await log_mod(f"Banned guild {gid} by {interaction.user}.")

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@app_commands.describe(guild_id="Numeric guild ID")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
        return
    gid = to_int(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("❌ Guild ID not in banned list.", ephemeral=True)
        return
    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Unbanned guild `{gid}`.", ephemeral=True)
    await log_mod(f"Unbanned guild {gid} by {interaction.user}.")

# ---- Tempban / Unban User ----
@tree.command(name="tempban", description="Temporarily ban a user (minutes)")
@app_commands.describe(user="User to ban", minutes="Duration in minutes")
async def tempban(interaction: discord.Interaction, user: discord.User, minutes: int):
    if not await is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
        return
    ts = int((datetime.utcnow() + timedelta(minutes=minutes)).timestamp())
    TEMP_BANS[str(user.id)] = ts
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"✅ Temporarily banned {user} for {minutes} minutes.", ephemeral=True)
    await log_mod(f"Tempbanned {user} for {minutes} minutes by {interaction.user}.")

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@app_commands.describe(user="User to unban")
async def unban_user(interaction: discord.Interaction, user: discord.User):
    if not await is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
        return
    removed = False
    if str(user.id) in TEMP_BANS:
        TEMP_BANS.pop(str(user.id))
        removed = True
    if user.id in BANNED_USERS:
        BANNED_USERS.remove(user.id)
        removed = True
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ Unbanned {user}.", ephemeral=True)
    if removed: await log_mod(f"Unbanned user {user} by {interaction.user}.")

# ---- Maintenance ----
@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
async def maintenance(interaction: discord.Interaction):
    if not await is_owner(interaction.user.id):
        await interaction.response.send_message("❌ Only bot owner can run this.", ephemeral=True)
        return
    MAINTENANCE["enabled"] = not MAINTENANCE.get("enabled", False)
    save_json(MAINT_FILE, MAINTENANCE)
    status = "enabled" if MAINTENANCE["enabled"] else "disabled"
    await interaction.response.send_message(f"⚠️ Maintenance mode {status}.", ephemeral=True)
    await log_mod(f"Maintenance mode {status} by {interaction.user}.")

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    for g in client.guilds: print(f"{g.name} | {g.id}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Setup hook for tempban loop ----
class MyClient(discord.Client):
    async def setup_hook(self):
        await tree.sync()
        self.loop.create_task(tempban_loop())

async def tempban_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        now = int(datetime.utcnow().timestamp())
        expired = [uid for uid, ts in TEMP_BANS.items() if ts <= now]
        for uid in expired:
            TEMP_BANS.pop(uid)
            save_json(TEMP_BANS_FILE, TEMP_BANS)
            user = client.get_user(int(uid))
            if user:
                await log_mod(f"Tempban expired for {user}.")
        await asyncio.sleep(60)

# ---- Run client ----
client = MyClient(intents=intents)
client.run(TOKEN)
