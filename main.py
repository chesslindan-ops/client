import os
import re
import json
import io
import threading
import asyncio
import discord
from discord import app_commands
from discord.ext import tasks
import aiohttp
from flask import Flask
from datetime import datetime, timedelta

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- Owner and modlog ----
OWNER_IDS = [1329161792936476683, 903569932791463946]
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
    print(f"[DEBUG] Flask keep-alive running on {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Discord bot setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Helpers ----
def to_int(val):
    try:
        return int(val)
    except:
        return None

async def is_owner(interaction: discord.Interaction):
    return interaction.user.id in OWNER_IDS

def now_timestamp():
    return datetime.utcnow().isoformat()

async def log_mod_action(action: str):
    channel = client.get_channel(MODLOG_CHANNEL_ID)
    if channel:
        embed = discord.Embed(
            title="🛠 Mod Action",
            description=action,
            color=0xFFA500,
            timestamp=datetime.utcnow()
        )
        await channel.send(embed=embed)

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
    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied ❌️",
            description="ℹ️ This bot is no longer associated with this server.\nDM @h.aze.l to appeal.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # Maintenance mode check
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
# ---- Admin commands: ban/unban guilds ----
@tree.command(name="ban_guild", description="Add a guild ID to the banned list (owner-only).")
@app_commands.describe(guild_id="Numeric guild ID")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("Invalid guild ID.", ephemeral=True)
        return
    if gid in BANNED_GUILDS:
        await interaction.response.send_message("Guild already banned.", ephemeral=True)
        return

    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild `{gid}` ✅", ephemeral=True)
    await log_mod_action(f"Guild `{gid}` was banned by {interaction.user}.")

@tree.command(name="unban_guild", description="Remove a guild from the banned list (owner-only).")
@app_commands.describe(guild_id="Numeric guild ID")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    gid = to_int(guild_id)
    if not gid or gid not in BANNED_GUILDS:
        await interaction.response.send_message("Guild ID not found in banned list.", ephemeral=True)
        return

    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Unbanned guild `{gid}` ✅", ephemeral=True)
    await log_mod_action(f"Guild `{gid}` was unbanned by {interaction.user}.")

# ---- Admin commands: ban/unban users ----
@tree.command(name="ban_user", description="Ban a user permanently (owner-only).")
@app_commands.describe(user_id="Numeric user ID")
async def ban_user(interaction: discord.Interaction, user_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return

    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        return
    if uid in BANNED_USERS:
        await interaction.response.send_message("User already banned.", ephemeral=True)
        return

    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User `{uid}` banned ✅", ephemeral=True)
    await log_mod_action(f"User `{uid}` was banned by {interaction.user}.")

@tree.command(name="unban_user", description="Unban a user (owner-only).")
@app_commands.describe(user_id="Numeric user ID")
async def unban_user(interaction: discord.Interaction, user_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return

    uid = to_int(user_id)
    if not uid or uid not in BANNED_USERS:
        await interaction.response.send_message("User not in banned list.", ephemeral=True)
        return

    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User `{uid}` unbanned ✅", ephemeral=True)
    await log_mod_action(f"User `{uid}` was unbanned by {interaction.user}.")

# ---- Temporary ban ----
@tree.command(name="tempban", description="Temporarily ban a user (owner-only).")
@app_commands.describe(user_id="Numeric user ID", minutes="Duration in minutes")
async def tempban(interaction: discord.Interaction, user_id: str, minutes: int):
    if not await is_owner(interaction):
        await interaction.response.send_message("Owner only.", ephemeral=True)
        return

    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("Invalid user ID.", ephemeral=True)
        return

    end_time = datetime.utcnow() + timedelta(minutes=minutes)
    TEMP_BANS[str(uid)] = end_time.isoformat()
    save_json(TEMP_BANS_FILE, TEMP_BANS)
    await interaction.response.send_message(f"User `{uid}` temporarily banned for {minutes} min ✅", ephemeral=True)
    await log_mod_action(f"User `{uid}` tempbanned by {interaction.user} for {minutes} minutes.")

# ---- Background task: auto-unban tempbans ----
@tasks.loop(minutes=1)
async def tempban_check():
    to_remove = []
    for uid, end_iso in TEMP_BANS.items():
        end_time = datetime.fromisoformat(end_iso)
        if datetime.utcnow() >= end_time:
            to_remove.append(uid)
    for uid in to_remove:
        TEMP_BANS.pop(uid, None)
        BANNED_USERS.remove(int(uid)) if int(uid) in BANNED_USERS else None
        save_json(TEMP_BANS_FILE, TEMP_BANS)
        save_json(BANNED_USERS_FILE, BANNED_USERS)
        await log_mod_action(f"Temporary ban expired for user `{uid}`.")

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands synced and ready!")
    tempban_check.start()
    print(f"Current banned guilds: {BANNED_GUILDS}")
    print(f"Current banned users: {BANNED_USERS}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run Flask in background thread ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Async main entry ----
async def main():
    async with client:
        await client.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
