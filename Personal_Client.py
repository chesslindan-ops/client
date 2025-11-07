import os
import re
import threading
import json
import time
import discord
from discord import app_commands
import aiohttp
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
MAINTENANCE = load_json(MAINT_FILE, {}).get("enabled", False)

def save_maintenance(state: bool):
    global MAINTENANCE
    MAINTENANCE = state
    save_json(MAINT_FILE, {"enabled": state})

# ---- Owner ID ----
OWNER_ID = 1329161792936476683

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

async def check_user_ban(interaction: discord.Interaction):
    if interaction.user.id in BANNED_USERS:
        await interaction.response.send_message(
            "Error ⚠️: User is banned from using this program ❌ | DM h.aze.l to appeal.",
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

# ---- Global rate limit ----
LAST_USE_TIMESTAMP = 0
COOLDOWN_SECONDS = 60

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    global LAST_USE_TIMESTAMP

    if await check_user_ban(interaction):
        return

    # global rate limit check
    now = time.time()
    if now - LAST_USE_TIMESTAMP < COOLDOWN_SECONDS:
        remaining = int(COOLDOWN_SECONDS - (now - LAST_USE_TIMESTAMP))
        await interaction.response.send_message(
            f"⚠️ Bot is on cooldown. Try again in {remaining} seconds.", ephemeral=True
        )
        return
    LAST_USE_TIMESTAMP = now

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
# (All owner commands from your original code remain unchanged...)

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
