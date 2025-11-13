# main.py  - FULL (modified only to add no_appeal flag + timestamp)
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

# ---- Secrets / config ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
OWNER_ID = int(os.getenv("OWNER_ID", "1329161792936476683"))

# ---- JSON files ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"
if not os.path.exists("seen_links.json"):
    with open("seen_links.json", "w") as f:
        json.dump({}, f)
# ---- load / save helpers ----
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] saving {path}: {e}")

# ---- in-memory data ----
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
intents.guilds = True
intents.members = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- simple helpers ----
def to_int(val):
    try:
        return int(val)
    except Exception:
        return None

def find_banned_user_entry(uid: int):
    """Return the ban entry (dict) or a dict wrapper for ints, or None."""
    for entry in BANNED_USERS:
        if isinstance(entry, dict) and entry.get("id") == uid:
            return entry
        if not isinstance(entry, dict) and entry == uid:
            return {"id": uid, "reason": "No reason recorded"}
    return None

def find_banned_guild_entry(gid: int):
    for entry in BANNED_GUILDS:
        if isinstance(entry, dict) and entry.get("id") == gid:
            return entry
        if not isinstance(entry, dict) and entry == gid:
            return {"id": gid, "reason": "No reason recorded", "name": None}
    return None

def is_tempbanned(uid: int):
    now = time.time()
    removed_any = False
    for entry in TEMP_BANS[:]:
        if entry.get("expires", 0) <= now:
            TEMP_BANS.remove(entry)
            removed_any = True
        elif entry.get("id") == uid:
            return entry
    if removed_any:
        save_tempbans()
    return None

async def check_user_ban(interaction: discord.Interaction):
    """
    If user is banned or tempbanned, send an ephemeral response that includes the reason
    and return True. Otherwise return False.
    """
    uid = interaction.user.id

    # check permanent bans
    entry = find_banned_user_entry(uid)
    if entry:
        reason = entry.get("reason", "No reason provided")
        ts = entry.get("timestamp")
        ts_text = f"\nBanned at: <t:{int(ts)}:F>" if ts else ""
        no_appeal = entry.get("no_appeal", False)
        appeal_text = "\nThis ban cannot be appealed." if no_appeal else "\nIf you believe this is a mistake, DM **@h.aze.l**."
        await interaction.response.send_message(
            f"🚫 You are banned from using this bot.\n**Reason:** {reason}{ts_text}{appeal_text}",
            ephemeral=True,
        )
        return True

    # check tempbans
    tentry = is_tempbanned(uid)
    if tentry:
        reason = tentry.get("reason", "No reason provided")
        expires = int(tentry.get("expires", time.time()))
        # tempbans may optionally include no_appeal if you later add it; handle gracefully:
        no_appeal = tentry.get("no_appeal", False)
        appeal_text = "\nThis ban cannot be appealed." if no_appeal else ""
        await interaction.response.send_message(
            f"⏳ You are temporarily banned from this bot.\n**Reason:** {reason}\nBan expires: <t:{expires}:F>{appeal_text}",
            ephemeral=True,
        )
        return True

    return False

async def check_guild_ban(interaction: discord.Interaction):
    """
    If guild is banned, send an embed with reason and return True. Else False.
    """
    gid = interaction.guild_id
    if gid is None:
        return False
    entry = find_banned_guild_entry(gid)
    if entry:
        reason = entry.get("reason", "No reason provided")
        name = entry.get("name") or (interaction.guild.name if interaction.guild else "Unknown")
        ts = entry.get("timestamp")
        ts_text = f"\nBanned at: <t:{int(ts)}:F>" if ts else ""
        no_appeal = entry.get("no_appeal", False)
        appeal_text = "\nThis ban cannot be appealed." if no_appeal else "\n Contact **@h.aze.l** to appeal."
        embed = discord.Embed(
            title="Access Denied ❌",
            description=f"This server is blacklisted from using this bot.\n**Server:** {name}\n**Reason:** {reason}{ts_text}{appeal_text}",
            color=discord.Color.red(),
        )
        embed.set_thumbnail(url="https://toppng.com/uploads/preview/red-cross-mark-download-png-red-cross-check-mark-11562934675swbmqcbecx.png")
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return True
    return False
# ---- Fetch group posts ----
MEMORY_FILE = "seen_links.json"

def load_seen_links():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)  # dict of guild_id -> list
        except:
            return {}
    return {}

def save_seen_links(data):
    with open(MEMORY_FILE, "w") as f:
        json.dump(data, f)
def clean_old_links():
    data = load_seen_links()
    modified = False
    for gid, links in data.items():
        if len(links) > 1000:  # cap at 1000 stored links per guild
            data[gid] = links[-500:]  # keep only the most recent 500
            modified = True
    if modified:
        save_seen_links(data)
        print("🧹 cleaned old links from memory file")
async def fetch_group_posts(guild_id=None):
    if not GROUP_ID:
        return []

    # load or init guild-specific memory
    seen_links = load_seen_links()
    if str(guild_id) not in seen_links:
        seen_links[str(guild_id)] = []

    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"} if ROBLOX_COOKIE else {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"⚠️ Failed to fetch posts: {resp.status}")
                    return []
                data = await resp.json()
    except Exception as e:
        print(f"[ERROR] fetch_group_posts: {e}")
        return []

    unique_links = []
    existing = set(seen_links[str(guild_id)])

    for post in data.get("data", []):
        content = post.get("body", "")
        # only accept /share/ links
        found = re.findall(r"https?://www\.roblox\.com/share(?:[/?][A-Za-z0-9_\-=&?#%]+)?", content)

        for link in found:
            if link not in existing:
                existing.add(link)
                unique_links.append(link)

    # save updated memory
    seen_links[str(guild_id)] = list(existing)
    if unique_links:
        save_seen_links(seen_links)

    return unique_links


# ---- Maintenance flag ----
MAINTENANCE = False
def set_maintenance(state: bool):
    global MAINTENANCE
    MAINTENANCE = state


# ---- Owner-only check decorator ----
def owner_only():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)


# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    # guild ban check
    if await check_guild_ban(interaction):
        return
    # user ban check
    if await check_user_ban(interaction):
        return

    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts(interaction.guild_id)
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return

    pretty = [f"[Click Here ({i})]({l})" for i, l in enumerate(links[:10], start=1)]
    message = "\n\n".join(pretty)

    title = "⚠️ Latest SAB Scammer PS Links 🔗"
    if MAINTENANCE:
        title = "⚠️ Maintenance Mode 🟠 | Latest SAB Scammer Links 🔗"
        message = f"⚠️ The bot is currently in maintenance mode and may experience issues.\n\n{message}"

    embed = discord.Embed(
        title=title,
        description=message,
        color=0x00ffcc if not MAINTENANCE else 0xFFA500
    )
    embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")

    await interaction.followup.send(embed=embed)


# ---- /onelink command ----
@tree.command(name="onelink", description="Get the first scammer private server link with a button")
async def onelink_command(interaction: discord.Interaction):
    try:
        # guild + user ban checks
        if await check_guild_ban(interaction):
            return
        if await check_user_ban(interaction):
            return

        await interaction.response.defer(thinking=True)
        links = await fetch_group_posts(interaction.guild_id)
        if not links:
            await interaction.followup.send("No roblox.com/share links found 😢", ephemeral=True)
            return

        first_link = links[0]
        view = View()
        view.add_item(Button(label="Click Here 🔗", url=first_link, style=discord.ButtonStyle.link))

        color = 0x00ffcc if not MAINTENANCE else 0xFFA500
        embed = discord.Embed(
            title="⚠️ Latest SAB Scammer PS Link 🔗",
            description="Click the button below to visit the link.",
            color=color
        )
        embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
        embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")

        await interaction.followup.send(embed=embed, view=view)

    except Exception as e:
        print(f"[ERROR] /onelink: {e}")
        try:
            await interaction.followup.send(f"⚠️ Error while running command:\n```{e}```", ephemeral=True)
        except:
            pass

# ---- Ban / Unban users (with reasons) ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban", reason="Reason for the ban", no_appeal="True if ban cannot be appealed")
async def ban_user(interaction: discord.Interaction, user_id: str, reason: str, no_appeal: bool):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if find_banned_user_entry(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    entry = {"id": uid, "reason": reason, "timestamp": int(time.time()), "no_appeal": no_appeal}
    BANNED_USERS.append(entry)
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    await interaction.response.send_message(f"✅ User `{uid}` banned.\n**Reason:** {reason}", ephemeral=True)

@tree.command(name="unban_user", description="Unban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    removed = False
    for e in BANNED_USERS[:]:
        if (isinstance(e, dict) and e.get("id") == uid) or (not isinstance(e, dict) and e == uid):
            BANNED_USERS.remove(e)
            removed = True
    save_json(BANNED_USERS_FILE, BANNED_USERS)
    # also remove tempbans if any
    for e in TEMP_BANS[:]:
        if e.get("id") == uid:
            TEMP_BANS.remove(e)
            removed = True
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` unbanned." if removed else "⚠️ User was not banned.", ephemeral=True)

@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to tempban", duration_minutes="Duration in minutes", reason="Reason for tempban")
async def tempban(interaction: discord.Interaction, user_id: str, duration_minutes: int, reason: str):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if find_banned_user_entry(uid) or is_tempbanned(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    expires_at = time.time() + max(1, duration_minutes) * 60
    TEMP_BANS.append({"id": uid, "expires": expires_at, "reason": reason})
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes.\n**Reason:** {reason}", ephemeral=True)
    # main.py - PART 2 (append after PART 1)

# ---- Guild bans / invite ban ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to ban", reason="Reason for guild ban", no_appeal="True if ban cannot be appealed")
async def ban_guild(interaction: discord.Interaction, guild_id: str, reason: str, no_appeal: bool):
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if find_banned_guild_entry(gid):
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    g = client.get_guild(gid)
    name = g.name if g else None
    entry = {"id": gid, "name": name, "reason": reason, "timestamp": int(time.time()), "no_appeal": no_appeal}
    BANNED_GUILDS.append(entry)
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{name or gid}` banned.\n**Reason:** {reason}", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    removed = False
    for e in BANNED_GUILDS[:]:
        if (isinstance(e, dict) and e.get("id") == gid) or (not isinstance(e, dict) and e == gid):
            BANNED_GUILDS.remove(e)
            removed = True
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild `{gid}` unbanned." if removed else "⚠️ Guild not in banned list.", ephemeral=True)

@tree.command(name="ban_invite", description="Ban a guild by invite (owner-only)")
@owner_only()
@app_commands.describe(invite="Invite code or URL", reason="Reason for ban", no_appeal="True if ban cannot be appealed")
async def ban_invite(interaction: discord.Interaction, invite: str, reason: str, no_appeal: bool):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("❌ Could not parse invite.", ephemeral=True)
        return
    code = m.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    await interaction.response.send_message(f"❌ Failed to resolve invite (HTTP {resp.status}).", ephemeral=True)
                    return
                data = await resp.json()
    except Exception as e:
        await interaction.response.send_message(f"❌ Error fetching invite: {e}", ephemeral=True)
        return
    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("❌ Invite has no guild info.", ephemeral=True)
        return
    gid = int(guild["id"])
    name = guild.get("name", "Unknown")
    if find_banned_guild_entry(gid):
        await interaction.response.send_message(f"⚠️ Guild **{name}** already banned.", ephemeral=True)
        return
    # include no_appeal and timestamp
    BANNED_GUILDS.append({"id": gid, "name": name, "reason": reason, "timestamp": int(time.time()), "no_appeal": no_appeal})
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(
    f"✅ Guild `{name}` (ID: `{gid}`) banned.\n**Reason:** {reason}", ephemeral=True)
# ---- listing commands ----
@tree.command(name="list_banned", description="List all banned guilds (owner-only)")
@owner_only()
async def list_banned(interaction: discord.Interaction):
    lines = []
    for i, e in enumerate(BANNED_GUILDS, start=1):
        if isinstance(e, dict):
            gid = e.get("id")
            name = e.get("name") or (client.get_guild(gid).name if client.get_guild(gid) else "Unknown")
            reason = e.get("reason", "No reason recorded")
        else:
            gid = e
            name = (client.get_guild(gid).name if client.get_guild(gid) else "Unknown")
            reason = "No reason recorded"
        lines.append(f"{i}. {name} | {gid} | Reason: {reason}")
    text = "\n".join(lines) or "No banned guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Banned guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO()
        bio.write(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "banned_guilds.txt"), ephemeral=True)

@tree.command(name="list_banned_users", description="List all banned users (owner-only)")
@owner_only()
async def list_banned_users(interaction: discord.Interaction):
    lines = []
    for i, e in enumerate(BANNED_USERS, start=1):
        if isinstance(e, dict):
            uid = e.get("id")
            reason = e.get("reason", "No reason recorded")
            ts = e.get("timestamp")
            ts_text = f" | Banned at: {int(ts)}" if ts else ""
        else:
            uid = e
            reason = "No reason recorded"
            ts_text = ""
        lines.append(f"{i}. {uid} | Reason: {reason}{ts_text}")
    text = "\n".join(lines) or "No banned users."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Banned users:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO()
        bio.write(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "banned_users.txt"), ephemeral=True)

@tree.command(name="list_removed", description="List removed guilds (owner-only)")
@owner_only()
async def list_removed(interaction: discord.Interaction):
    lines = [f"{i+1}. {e.get('name','Unknown')} | {e.get('id','Unknown')}" for i, e in enumerate(REMOVED_GUILDS)]
    text = "\n".join(lines) or "No removed guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Removed guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO()
        bio.write(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "removed_guilds.txt"), ephemeral=True)

# ---- announce (global) ----
@tree.command(name="announce", description="Send a global announcement (owner-only)")
@owner_only()
@app_commands.describe(message="Message to announce globally (multi-line allowed)")
async def announce(interaction: discord.Interaction, message: str):
    embed = discord.Embed(
        title="Global Announcement From Developer/Global Raid Announcement",
        description=message,
        color=0x0000ff
    )
    sent_count = 0
    keywords = ("general", "raid", "link", "bot", "chat")

    for guild in client.guilds:
        target_channel = None
        for channel in guild.text_channels:
            name_lower = channel.name.lower()
            if any(k in name_lower for k in keywords):
                target_channel = channel
                break  # first matching channel

        if target_channel:
            try:
                await target_channel.send(embed=embed)
                sent_count += 1
            except:
                pass

    await interaction.response.send_message(f"✅ Announcement sent to {sent_count} guilds.", ephemeral=True)

# ---- maintenance toggle ----
@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
@owner_only()
@app_commands.describe(state="on/off")
async def maintenance_cmd(interaction: discord.Interaction, state: str):
    s = state.lower()
    if s not in ["on", "off"]:
        await interaction.response.send_message("use: /maintenance on  |  /maintenance off", ephemeral=True)
        return
    set_maintenance(s == "on")
    await interaction.response.send_message(f"maintenance set to **{s}**", ephemeral=True)

# ---- update_tree (sync) ----
@tree.command(name="update_tree", description="Sync slash commands (owner-only)")
@owner_only()
async def update_tree(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await tree.sync()
        await interaction.followup.send(f"✅ Commands tree synced! Total commands: {len(synced)}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands tree: {e}", ephemeral=True)

# ---- events ----
@client.event
async def on_ready():
    try:
        await tree.sync()
    except Exception:
        pass
    print(f"✅ Logged in as {client.user}")
    print(f"In {len(client.guilds)} guilds.")
    total_members = sum(g.member_count for g in client.guilds if getattr(g, "member_count", None))
    print(f"Reaching approx {total_members} members.")
    print("Currently banned guild ids:", [ (e if not isinstance(e, dict) else e.get('id')) for e in BANNED_GUILDS ])

@client.event
async def on_guild_join(guild):
    print(f"Joined guild: {guild.name} | {guild.id}")

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    REMOVED_GUILDS.append({"id": guild.id, "name": guild.name})
    save_json(REMOVED_LOG, REMOVED_GUILDS)
@client.event
async def on_ready():
    print(f"✅ Logged in as {client.user}")
    
    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600 * 6)  # every 6 hours
            clean_old_links()

    client.loop.create_task(periodic_cleanup())
# ---- start services ----
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(TOKEN)
