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
from discord.ui import View, Button

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

def is_banned_user(uid: int):
    for entry in BANNED_USERS:
        if (entry == uid) or (isinstance(entry, dict) and entry.get("id") == uid):
            return True
    return False

def is_banned_guild(gid: int):
    for entry in BANNED_GUILDS:
        if (entry == gid) or (isinstance(entry, dict) and entry.get("id") == gid):
            return True
    return False

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
    if is_banned_user(uid) or is_tempbanned(uid):
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
    if is_banned_guild(interaction.guild_id):
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

# ---- Ban / Unban users ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban", reason="Reason for ban")
async def ban_user(interaction: discord.Interaction, user_id: str, reason: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    if is_banned_user(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return

    BANNED_USERS.append({"id": uid, "reason": reason, "timestamp": time.time()})
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` banned for: {reason}", ephemeral=True)

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
    for entry in BANNED_USERS[:]:
        if (entry == uid) or (isinstance(entry, dict) and entry.get("id") == uid):
            BANNED_USERS.remove(entry)
            removed = True
    save_json(BANNED_USERS_FILE, BANNED_USERS)

    for entry in TEMP_BANS[:]:
        if entry["id"] == uid:
            TEMP_BANS.remove(entry)
            removed = True
    save_tempbans()

    msg = f"✅ User `{uid}` has been unbanned." if removed else "⚠️ User was not banned."
    await interaction.response.send_message(msg, ephemeral=True)

@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to tempban", duration_minutes="Duration in minutes", reason="Reason for tempban")
async def tempban(interaction: discord.Interaction, user_id: str, duration_minutes: int, reason: str):
    try:
        uid = int(user_id)
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    if is_banned_user(uid) or is_tempbanned(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return

    expires_at = time.time() + duration_minutes * 60
    TEMP_BANS.append({"id": uid, "expires": expires_at, "reason": reason})
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes.\nReason: {reason}", ephemeral=True)

# ---- Guild bans ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to ban", reason="Reason for guild ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str, reason: str):
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if is_banned_guild(gid):
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    g = client.get_guild(gid)
    name = g.name if g else "Unknown"
    BANNED_GUILDS.append({"id": gid, "name": name, "reason": reason, "timestamp": time.time()})
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{name}` banned for: {reason}", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int_gid(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    removed = False
    for entry in BANNED_GUILDS[:]:
        if (entry == gid) or (isinstance(entry, dict) and entry.get("id") == gid):
            BANNED_GUILDS.remove(entry)
            removed = True
    save_json(BANNED_FILE, BANNED_GUILDS)
    msg = f"✅ Guild `{gid}` unbanned." if removed else "⚠️ Guild not in banned list."
    await interaction.response.send_message(msg, ephemeral=True)

# ---- List banned ----
@tree.command(name="list_banned", description="List all banned guilds (owner-only)")
@owner_only()
async def list_banned(interaction: discord.Interaction):
    lines = []
    for i, e in enumerate(BANNED_GUILDS, start=1):
        if isinstance(e, dict):
            gid, name, reason = e.get("id"), e.get("name", "Unknown"), e.get("reason", "No reason recorded")
        else:
            gid, name, reason = e, "Unknown", "No reason recorded"
        lines.append(f"{i}. {name} | {gid} | Reason: {reason}")
    text = "\n".join(lines) or "No banned guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Banned guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.write(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "banned_guilds.txt"), ephemeral=True)

# ---- /onelink command ----
@tree.command(name="onelink", description="Get the first scammer private server link with a button")
async def onelink_command(interaction: discord.Interaction):
    try:
        if is_banned_guild(interaction.guild_id):
            embed = discord.Embed(
                title="Access Denied ❌️",
                description="This server is blacklisted.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        if await check_user_ban(interaction):
            return

        await interaction.response.defer(thinking=True)
        links = await fetch_group_posts()
        if not links:
            await interaction.followup.send("No roblox.com/share links found 😢", ephemeral=True)
            return
        first_link = links[0]
        view = View()
        view.add_item(Button(label="Click Here 🔗", url=first_link, style=discord.ButtonStyle.link))
        color = 0xFFA500 if MAINTENANCE else 0x00ffcc
        embed = discord.Embed(title="⚠️ Latest SAB Scammer PS Link 🔗", description="Click the button below to visit.", color=color)
        embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
        embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
        await interaction.followup.send(embed=embed, view=view)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error:\n```{e}```", ephemeral=True)

# ---- Sync ----
@tree.command(name="update_tree", description="Sync slash commands (owner-only)")
@owner_only()
async def update_tree(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await tree.sync()
        await interaction.followup.send(f"✅ Commands tree synced! Total: {len(synced)}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync: {e}", ephemeral=True)

# ---- Events ----
@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Guilds:", [f"{g.name} | {g.id}" for g in client.guilds])

@client.event
async def on_guild_remove(guild):
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)

# ---- Run ----
threading.Thread(target=run_flask).start()
client.run(TOKEN)
