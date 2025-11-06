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

# ---- Helper: owner check ----
async def is_owner(interaction: discord.Interaction) -> bool:
    try:
        app_info = await client.application_info()
        return interaction.user.id == app_info.owner.id
    except Exception:
        # fallback: be conservative
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
    if interaction.guild_id in BANNED_GUILDS:
        embed = discord.Embed(
            title="Access Denied",
            description="this guild is blocked from using this bot.",
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

# ---- Admin commands: ban/unban (owner-only) ----
@tree.command(name="ban_guild", description="Add a guild ID to the bot's banned list (owner-only).")
@app_commands.describe(guild_id="Numeric guild ID to ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("Invalid guild id. Use the numeric ID.", ephemeral=True)
        return

    if gid in BANNED_GUILDS:
        await interaction.response.send_message("That guild is already banned.", ephemeral=True)
        return

    BANNED_GUILDS.append(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild id `{gid}` — added to list.", ephemeral=True)

@tree.command(name="unban_guild", description="Remove a guild ID from the banned list (owner-only).")
@app_commands.describe(guild_id="Numeric guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("Invalid guild id. Use the numeric ID.", ephemeral=True)
        return

    if gid not in BANNED_GUILDS:
        await interaction.response.send_message("That guild id is not in the banned list.", ephemeral=True)
        return

    BANNED_GUILDS.remove(gid)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Unbanned guild id `{gid}`.", ephemeral=True)

# ---- Ban by invite: resolves invite to guild id even if bot isn't in the server ----
@tree.command(name="ban_invite", description="Ban a guild using an invite code or invite URL (owner-only).")
@app_commands.describe(invite="Invite code or invite URL (e.g. abc123 or https://discord.gg/abc123)")
async def ban_invite(interaction: discord.Interaction, invite: str):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    # extract code
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("Couldn't parse invite. Send the code or full invite URL.", ephemeral=True)
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
        await interaction.response.send_message("Invite resolved but no guild info available.", ephemeral=True)
        return

    gid = guild.get("id")
    name = guild.get("name", "Unknown")
    try:
        gid_int = int(gid)
    except Exception:
        await interaction.response.send_message("Could not parse guild id from invite.", ephemeral=True)
        return

    if gid_int in BANNED_GUILDS:
        await interaction.response.send_message(f"Guild **{name}** (`{gid}`) is already banned.", ephemeral=True)
        return

    BANNED_GUILDS.append(gid_int)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"Banned guild **{name}** (`{gid}`).", ephemeral=True)

# ---- New: list_banned command ----
@tree.command(name="list_banned", description="List all banned guild IDs (owner-only).")
async def list_banned(interaction: discord.Interaction):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    if not BANNED_GUILDS:
        await interaction.followup.send("No banned guilds.", ephemeral=True)
        return

    # prepare readable text
    lines = []
    for i, gid in enumerate(BANNED_GUILDS, start=1):
        # try to resolve name if bot in that guild
        gobj = client.get_guild(gid)
        name = gobj.name if gobj else "Not in guild (bot not a member)"
        lines.append(f"{i}. {name} | {gid}")

    text = "\n".join(lines)
    # if short enough, send as ephemeral text, otherwise send as file
    if len(text) <= 1800:
        await interaction.followup.send(f"**Banned guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        file = discord.File(fp=bio, filename="banned_guilds.txt")
        await interaction.followup.send("Banned list is large — sending file.", file=file, ephemeral=True)

# ---- New: list_removed command ----
@tree.command(name="list_removed", description="List guilds the bot was removed from (owner-only).")
async def list_removed(interaction: discord.Interaction):
    if not await is_owner(interaction):
        await interaction.response.send_message("Only the bot owner can run this.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)
    if not REMOVED_GUILDS:
        await interaction.followup.send("No recorded removed guilds.", ephemeral=True)
        return

    # prepare readable text
    lines = []
    for i, entry in enumerate(REMOVED_GUILDS, start=1):
        gid = entry.get("id", "unknown")
        name = entry.get("name", "unknown")
        lines.append(f"{i}. {name} | {gid}")

    text = "\n".join(lines)
    if len(text) <= 1800:
        await interaction.followup.send(f"**Removed guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        file = discord.File(fp=bio, filename="removed_guilds.txt")
        await interaction.followup.send("Removed list is large — sending file.", file=file, ephemeral=True)

# ---- Events: print guilds, log removes, and react to guild join/remove ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash commands are synced and ready!")
    print("\nGuilds bot is in:")
    for g in client.guilds:
        print(f"{g.name} | {g.id}")
    print("_________________________")
    print(f"Currently banned guild ids: {BANNED_GUILDS}")

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    # log removal to file so you can inspect and ban later
    print(f"Removed from guild: {guild.name} | {guild.id}")
    entry = {"id": guild.id, "name": guild.name}
    REMOVED_GUILDS.append(entry)
    save_json(REMOVED_LOG, REMOVED_GUILDS)

    # optional: auto-add to removed list but not to ban list (preserve owner choice)
    # if you want immediate auto-ban on removal uncomment below:
    # if guild.id not in BANNED_GUILDS:
    #     BANNED_GUILDS.append(guild.id)
    #     save_json(BANNED_FILE, BANNED_GUILDS)

# ---- Run Flask in background thread ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Run Discord ----
client.run(TOKEN)
