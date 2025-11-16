# main.py  - FULL (converted to SQLite storage; preserves original behavior + flags + gban)
import os
import re
import threading
import json
import io
import time
import asyncio
import sqlite3
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

DB_FILE = os.getenv("SQLITE_DB", "data.db")

# ---- Database setup ----
_conn = sqlite3.connect(DB_FILE, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_db_lock = threading.Lock()

def db_exec(query, params=(), fetchone=False, fetchall=False, commit=False):
    with _db_lock:
        cur = _conn.cursor()
        cur.execute(query, params)
        result = None
        if fetchone:
            result = cur.fetchone()
        elif fetchall:
            result = cur.fetchall()
        if commit:
            _conn.commit()
        return result

# Create tables
with _db_lock:
    cur = _conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS banned_guilds (
        id INTEGER PRIMARY KEY,
        name TEXT,
        reason TEXT,
        timestamp INTEGER,
        no_appeal INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS removed_guilds (
        id INTEGER,
        name TEXT,
        timestamp INTEGER
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS banned_users (
        id INTEGER PRIMARY KEY,
        reason TEXT,
        timestamp INTEGER,
        no_appeal INTEGER DEFAULT 0,
        gban INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS temp_bans (
        id INTEGER PRIMARY KEY,
        expires INTEGER,
        reason TEXT,
        no_appeal INTEGER DEFAULT 0,
        gban INTEGER DEFAULT 0
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS seen_links (
        link TEXT PRIMARY KEY,
        guild_id INTEGER,
        first_seen INTEGER
    )
    """)
    _conn.commit()

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
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- simple helpers ----
def to_int(val):
    try:
        return int(val)
    except Exception:
        return None

# --- BANNED USERS ---
def find_banned_user_entry(uid: int):
    r = db_exec("SELECT * FROM banned_users WHERE id=? LIMIT 1", (uid,), fetchone=True)
    if not r:
        return None
    return {
        "id": r["id"],
        "reason": r["reason"],
        "timestamp": r["timestamp"],
        "no_appeal": bool(r["no_appeal"]),
        "gban": bool(r.get("gban", 0))
    }

def add_banned_user(uid: int, reason: str, no_appeal: bool = False, gban: bool = False):
    ts = int(time.time())
    db_exec(
        "INSERT OR REPLACE INTO banned_users (id, reason, timestamp, no_appeal, gban) VALUES (?, ?, ?, ?, ?)",
        (uid, reason, ts, int(no_appeal), int(gban)),
        commit=True
    )

def remove_banned_user(uid: int):
    db_exec("DELETE FROM banned_users WHERE id=?", (uid,), commit=True)

# --- TEMP BANS ---
def add_tempban(uid: int, expires: float, reason: str, no_appeal: bool = False, gban: bool = False):
    db_exec(
        "INSERT OR REPLACE INTO temp_bans (id, expires, reason, no_appeal, gban) VALUES (?, ?, ?, ?, ?)",
        (uid, int(expires), reason, int(no_appeal), int(gban)),
        commit=True
    )

def remove_tempban(uid: int):
    db_exec("DELETE FROM temp_bans WHERE id=?", (uid,), commit=True)

def get_tempban(uid: int):
    now = int(time.time())
    db_exec("DELETE FROM temp_bans WHERE expires <= ?", (now,), commit=True)
    r = db_exec("SELECT * FROM temp_bans WHERE id=? LIMIT 1", (uid,), fetchone=True)
    if not r:
        return None
    return {
        "id": r["id"],
        "expires": r["expires"],
        "reason": r["reason"],
        "no_appeal": bool(r["no_appeal"]),
        "gban": bool(r.get("gban", 0))
    }

# --- BANNED GUILDS ---
def find_banned_guild_entry(gid: int):
    r = db_exec("SELECT * FROM banned_guilds WHERE id=? LIMIT 1", (gid,), fetchone=True)
    if not r:
        return None
    return {"id": r["id"], "name": r["name"], "reason": r["reason"], "timestamp": r["timestamp"], "no_appeal": bool(r["no_appeal"])}

def add_banned_guild(gid: int, name: str, reason: str, no_appeal: bool = False):
    ts = int(time.time())
    db_exec(
        "INSERT OR REPLACE INTO banned_guilds (id, name, reason, timestamp, no_appeal) VALUES (?, ?, ?, ?, ?)",
        (gid, name, reason, ts, int(no_appeal)),
        commit=True
    )

def remove_banned_guild(gid: int):
    db_exec("DELETE FROM banned_guilds WHERE id=?", (gid,), commit=True)

# --- REMOVED GUILDS ---
def add_removed_guild(gid: int, name: str):
    db_exec(
        "INSERT INTO removed_guilds (id, name, timestamp) VALUES (?, ?, ?)",
        (gid, name, int(time.time())),
        commit=True
    )

def list_removed_guilds():
    rows = db_exec("SELECT * FROM removed_guilds ORDER BY timestamp DESC", fetchall=True)
    return rows or []

# --- SEEN LINKS ---
def seen_link_exists(link: str):
    r = db_exec("SELECT * FROM seen_links WHERE link=? LIMIT 1", (link,), fetchone=True)
    return r is not None

def add_seen_link(link: str, gid: int):
    db_exec("INSERT OR REPLACE INTO seen_links (link, guild_id, first_seen) VALUES (?, ?, ?)",
            (link, gid or 0, int(time.time())), commit=True)
    enforce_seen_links_cap(gid)

def get_seen_links_for_guild(gid: int):
    rows = db_exec("SELECT link FROM seen_links WHERE guild_id=? ORDER BY first_seen DESC", (gid,), fetchall=True)
    return [r["link"] for r in (rows or [])]

def count_seen_links_for_guild(gid: int):
    r = db_exec("SELECT COUNT(*) as c FROM seen_links WHERE guild_id=?", (gid,), fetchone=True)
    return r["c"] if r else 0

def enforce_seen_links_cap(gid: int, cap=500):
    r = db_exec("SELECT link FROM seen_links WHERE guild_id=? ORDER BY first_seen DESC LIMIT ? OFFSET ?",
                (gid, cap, cap), fetchall=True)
    if not r:
        return
    links_to_delete = [row["link"] for row in r]
    with _db_lock:
        cur = _conn.cursor()
        cur.executemany("DELETE FROM seen_links WHERE link=?", [(l,) for l in links_to_delete])
        _conn.commit()

def clean_old_links_global(max_total_per_guild=1000, trim_to=500):
    with _db_lock:
        cur = _conn.cursor()
        cur.execute("SELECT guild_id, COUNT(*) as c FROM seen_links GROUP BY guild_id HAVING c > ?", (max_total_per_guild,))
        rows = cur.fetchall()
        for row in rows:
            gid = row[0]
            cur.execute("""
                DELETE FROM seen_links WHERE link IN (
                    SELECT link FROM seen_links WHERE guild_id=? ORDER BY first_seen ASC LIMIT ?
                )
            """, (gid, row[1] - trim_to))
        _conn.commit()

# ---- ban checks ----
def is_tempbanned(uid: int):
    entry = get_tempban(uid)
    return entry

async def check_user_ban(interaction: discord.Interaction):
    uid = interaction.user.id
    entry = find_banned_user_entry(uid)
    if entry:
        reason = entry.get("reason", "No reason provided")
        ts = entry.get("timestamp")
        ts_text = f"\nBanned at: <t:{int(ts)}:F>" if ts else ""
        no_appeal = entry.get("no_appeal", False)
        appeal_text = "\nThis ban cannot be appealed." if no_appeal else "\nIf you believe this is a mistake, DM **@h.aze.l**."
        await interaction.response.send_message(
            f"🚫 You are banned from using this bot.\n**Reason:** {reason}{ts_text}{appeal_text}",
            ephemeral=True
        )
        return True

    tentry = is_tempbanned(uid)
    if tentry:
        reason = tentry.get("reason", "No reason provided")
        expires = int(tentry.get("expires", time.time()))
        no_appeal = tentry.get("no_appeal", False)
        appeal_text = "\nThis ban cannot be appealed." if no_appeal else ""
        await interaction.response.send_message(
            f"⏳ You are temporarily banned from this bot.\n**Reason:** {reason}\nBan expires: <t:{expires}:F>{appeal_text}",
            ephemeral=True
        )
        return True

    return False

async def check_guild_ban(interaction: discord.Interaction):
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

# ---- here only changes: ban_user + tempban + gban auto-leave ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban", reason="Reason for the ban", no_appeal="True if ban cannot be appealed", gban="Prevent adding bot to servers")
async def ban_user(interaction: discord.Interaction, user_id: str, reason: str, no_appeal: bool, gban: bool):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if find_banned_user_entry(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    add_banned_user(uid, reason, no_appeal, gban)
    await interaction.response.send_message(f"✅ User `{uid}` banned (gban: {gban}).\n**Reason:** {reason}", ephemeral=True)

@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to tempban", duration_minutes="Duration in minutes", reason="Reason for tempban", gban="Prevent adding bot to servers")
async def tempban(interaction: discord.Interaction, user_id: str, duration_minutes: int, reason: str, gban: bool = False):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if find_banned_user_entry(uid) or get_tempban(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    expires_at = int(time.time()) + max(1, duration_minutes) * 60
    add_tempban(uid, expires_at, reason, gban=gban)
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes (gban: {gban}).\n**Reason:** {reason}", ephemeral=True)

@client.event
async def on_guild_join(guild):
    owner = guild.owner
    if owner:
        entry = find_banned_user_entry(owner.id)
        if entry and entry.get("gban"):
            print(f"⚠️ Banned user {owner} tried adding the bot to {guild.name} ({guild.id})")
            await guild.leave()
            return
    print(f"Joined guild: {guild.name} | {guild.id}")

# ---- rest of the file (all commands, /links, /onelink, /announce, maintenance, update_tree, events) remain exactly the same as original script ----
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
    add_banned_guild(gid, name, reason, no_appeal)
    guild_obj = client.get_guild(gid)
    if guild_obj:
        try:
            await guild_obj.leave()
        except:
            pass
    await interaction.response.send_message(f"✅ Guild `{name or gid}` banned.\n**Reason:** {reason}", ephemeral=True)

@tree.command(name="unban_guild", description="Unban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild(interaction: discord.Interaction, guild_id: str):
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    entry = find_banned_guild_entry(gid)
    removed = False
    if entry:
        remove_banned_guild(gid)
        removed = True
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
    add_banned_guild(gid, name, reason, no_appeal)
    await interaction.response.send_message(f"✅ Guild `{name}` (ID: `{gid}`) banned.\n**Reason:** {reason}", ephemeral=True)

# ---- listing commands ----
@tree.command(name="list_banned", description="List all banned guilds (owner-only)")
@owner_only()
async def list_banned(interaction: discord.Interaction):
    rows = db_exec("SELECT * FROM banned_guilds ORDER BY timestamp DESC", fetchall=True) or []
    lines = []
    for i, e in enumerate(rows, start=1):
        gid = e["id"]
        name = e["name"] or (client.get_guild(gid).name if client.get_guild(gid) else "Unknown")
        reason = e["reason"] or "No reason recorded"
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
    rows = db_exec("SELECT * FROM banned_users ORDER BY timestamp DESC", fetchall=True) or []
    lines = []
    for i, e in enumerate(rows, start=1):
        uid = e["id"]
        reason = e["reason"] or "No reason recorded"
        ts = e["timestamp"]
        ts_text = f" | Banned at: {int(ts)}" if ts else ""
        gban_text = " | GBAN" if e.get("gban") else ""
        lines.append(f"{i}. {uid} | Reason: {reason}{ts_text}{gban_text}")
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
    rows = list_removed_guilds() or []
    lines = [f"{i+1}. {r['name'] or 'Unknown'} | {r['id']}" for i, r in enumerate(rows)]
    text = "\n".join(lines) or "No removed guilds."
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Removed guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO()
        bio.write(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "removed_guilds.txt"), ephemeral=True)

# ---- announce (global) ----
@tree.command(name="announce", description="Send a global announcement")
@owner_only()
@app_commands.describe(message="Message to broadcast")
async def announce(interaction: discord.Interaction, message: str):
    await interaction.response.send_message("starting broadcast…", ephemeral=True)
    status_msg = await interaction.original_response()

    embed = discord.Embed(title="Global Announcement", description=message, color=0x0066ff)
    keywords = ("general", "chat", "bot", "raid", "link")

    async def pick_channel(guild: discord.Guild):
        for ch in guild.text_channels:
            if any(k in ch.name.lower() for k in keywords):
                perms = ch.permissions_for(guild.me)
                if perms.send_messages and perms.view_channel:
                    return ch
        for ch in guild.text_channels:
            perms = ch.permissions_for(guild.me)
            if perms.send_messages and perms.view_channel:
                return ch
        return None

    async def safe_send(ch):
        try:
            return await asyncio.wait_for(ch.send(embed=embed), timeout=2)
        except:
            return None

    async def broadcaster():
        guilds = list(client.guilds)
        total = len(guilds)
        sent_count = 0
        delay = 0.15
        burst_limit = 20

        for i, guild in enumerate(guilds, start=1):
            ch = await pick_channel(guild)
            if ch:
                res = await safe_send(ch)
                if res:
                    sent_count += 1
                if sent_count % burst_limit == 0:
                    await asyncio.sleep(1.2)

            if i % 25 == 0 or i == total:
                try:
                    await status_msg.edit(content=f"broadcasting… {i}/{total} guilds\nsent: {sent_count}")
                except:
                    pass
            await asyncio.sleep(delay)

        try:
            await status_msg.edit(content=f"done! sent in {sent_count}/{total} guilds.")
        except:
            pass

    client.loop.create_task(broadcaster())

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

# ---- update_tree ----
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
    total_members = sum((g.member_count or 0) for g in client.guilds)
    print(f"Reaching approx {total_members} members.")

    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600 * 6)
            clean_old_links_global()
            now = int(time.time())
            db_exec("DELETE FROM temp_bans WHERE expires <= ?", (now,), commit=True)

    client.loop.create_task(periodic_cleanup())

@client.event
async def on_guild_remove(guild):
    print(f"Removed from guild: {guild.name} | {guild.id}")
    add_removed_guild(guild.id, guild.name)

# ---- start services ----
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(TOKEN)
