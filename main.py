import os
import re
import threading
import json
import io
import discord
from discord import app_commands
import aiohttp
from flask import Flask

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- File storage for bans / removed log ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"

# ---- NEW: user bans file ----
BANNED_USERS_FILE = "banned_users.json"

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

BANNED_GUILDS = load_json(BANNED_FILE, [])  # list of ints (guild ids)
REMOVED_GUILDS = load_json(REMOVED_LOG, [])  # list of {id, name, timestamp?}
BANNED_USERS = load_json(BANNED_USERS_FILE, [])  # list of ints (user ids)

# ---- Owner (hardcoded per your choice A) ----
OWNER_ID = 1329161792936476683

# ---- Flask setup ----
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

# ---- Helper: ensure guild id is an int ----
def to_int_gid(val):
    try:
        return int(val)
    except Exception:
        return None

# ---- Helper: owner check (uses hardcoded OWNER_ID) ----
async def is_owner(interaction: discord.Interaction) -> bool:
    try:
        return interaction.user.id == OWNER_ID
    except Exception:
        return False

# ---- fetch group posts (unchanged) ----
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
    
    # dedupe preserve order
    seen = set()
    unique_links = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique_links.append(l)
    return unique_links

# ---- /links command (keeps banned check) ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    # user ban check (Option A: only /links is affected)
    if interaction.user.id in BANNED_USERS:
        # exact string you provided, sent ephemeral
        await interaction.response.send_message(
            "Error ⚠️: User is banned from using this program ❌️ | DM h.aze.l to appeal.",
            ephemeral=True
        )
        return

    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied ❌️ Error Code JS0007",
            description="⚠️❌️ This guild is banned from using this bot. | Contact @h.aze.l to appeal.",
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
    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️", description=message, color=0x00ffcc)
    embed.set_footer(text="DM @h.aze.l for bug reports.| Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- ban / unban users ----
@tree.command(name="ban_user", description="Ban a user id from using the bot (owner only)")
@app_commands.describe(user_id="the numeric user id")
async def ban_user(interaction: discord.Interaction, user_id: str):
    if not await is_owner(interaction):
        return await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)

    try:
        uid = int(user_id)
    except Exception:
        return await interaction.response.send_message("Invalid user id. Use the numeric ID.", ephemeral=True)

    if uid in BANNED_USERS:
        return await interaction.response.send_message("That user is already banned.", ephemeral=True)

    BANNED_USERS.append(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User `{uid}` has been banned.", ephemeral=True)


@tree.command(name="unban_user", description="Unban a user id from using the bot (owner only)")
@app_commands.describe(user_id="the numeric user id")
async def unban_user(interaction: discord.Interaction, user_id: str):
    if not await is_owner(interaction):
        return await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)

    try:
        uid = int(user_id)
    except Exception:
        return await interaction.response.send_message("Invalid user id. Use the numeric ID.", ephemeral=True)

    if uid not in BANNED_USERS:
        return await interaction.response.send_message("That user is not banned.", ephemeral=True)

    BANNED_USERS.remove(uid)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"User `{uid}` has been unbanned.", ephemeral=True)
# ---- Admin guild ban/unban (owner-only) ----
@tree.command(name="ban_guild", description="Ban a guild from using the bot (Owner only)")
@app_commands.describe(guild_id="the numeric guild id")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        return await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)

    gid = to_int_gid(guild_id)
    if not gid:
        return await interaction.response.send_message("Invalid guild id. Use the numeric ID.", ephemeral=True)

    if gid in BANNED_GUILDS:
        return await interaction.response.send_message("That guild is already banned.", ephemeral=True)

    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Guild `{gid}` has been banned ✅", ephemeral=True)


@tree.command(name="unban_guild", description="Unban a guild from using the bot (Owner only)")
@app_commands.describe(guild_id="the numeric guild id")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        return await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)

    gid = to_int_gid(guild_id)
    if not gid:
        return await interaction.response.send_message("Invalid guild id. Use the numeric ID.", ephemeral=True)

    if gid not in BANNED_GUILDS:
        return await interaction.response.send_message("That guild is not banned.", ephemeral=True)

    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Guild `{gid}` has been unbanned ✅", ephemeral=True)


# ---- on ready ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"ready as {client.user}")
    print("guilds:\n")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")


# ---- auto leave banned guilds (same behavior as before) ----


# ---- start flask thread + run bot ----
threading.Thread(target=run_flask).start()
client.run(TOKEN)
