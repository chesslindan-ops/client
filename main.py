# -----------------------------------------
# main.py  (PART 1)
# -----------------------------------------

import os
import re
import json
import time
import sqlite3
import threading
import asyncio
import discord
from discord import app_commands
from discord.ui import View, Button
from flask import Flask
import aiohttp

# -------------------------------
# CONSTANTS / ENV
# -------------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
OWNER_ID = int(os.getenv("OWNER_ID"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# -------------------------------
# FLASK KEEPALIVE
# -------------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot alive!", 200

def run_flask():
    app.run(host="0.0.0.0", port=8080)

threading.Thread(target=run_flask).start()

# -------------------------------
# SQLITE INIT
# -------------------------------
db = sqlite3.connect("data.db")
cursor = db.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS user_bans (
    user_id INTEGER PRIMARY KEY,
    reason TEXT,
    timestamp INTEGER,
    no_appeal INTEGER DEFAULT 0,
    gban INTEGER DEFAULT 0
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS guild_bans (
    guild_id INTEGER PRIMARY KEY,
    reason TEXT,
    timestamp INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS removed_guilds (
    guild_id INTEGER,
    name TEXT,
    timestamp INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS seen_links (
    link TEXT PRIMARY KEY,
    guild_id INTEGER,
    user_id INTEGER,
    timestamp INTEGER
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS uservan (
    guild_id INTEGER PRIMARY KEY,
    inviter_id INTEGER,
    inviter_name TEXT,
    timestamp INTEGER
)
""")

db.commit()

# -----------------------------------------------------
# UTILS WRAPPERS
# -----------------------------------------------------

def add_user_ban(uid, reason, no_appeal=False, gban=False):
    cursor.execute("""
        INSERT OR REPLACE INTO user_bans (user_id, reason, timestamp, no_appeal, gban)
        VALUES (?, ?, ?, ?, ?)
    """, (uid, reason, int(time.time()), int(no_appeal), int(gban)))
    db.commit()

def remove_user_ban(uid):
    cursor.execute("DELETE FROM user_bans WHERE user_id=?", (uid,))
    db.commit()

def is_gbanned(uid):
    r = cursor.execute("SELECT gban FROM user_bans WHERE user_id=?", (uid,)).fetchone()
    return r and r[0] == 1

def get_user_ban(uid):
    r = cursor.execute("SELECT * FROM user_bans WHERE user_id=?", (uid,)).fetchone()
    return r

def add_guild_ban(gid, reason):
    cursor.execute("""
        INSERT OR REPLACE INTO guild_bans (guild_id, reason, timestamp)
        VALUES (?, ?, ?)
    """, (gid, reason, int(time.time())))
    db.commit()

def remove_guild_ban(gid):
    cursor.execute("DELETE FROM guild_bans WHERE guild_id=?", (gid,))
    db.commit()

def is_guild_banned(gid):
    r = cursor.execute("SELECT * FROM guild_bans WHERE guild_id=?", (gid,)).fetchone()
    return r is not None

def add_seen_link(link, gid, uid):
    cursor.execute("""
        INSERT OR REPLACE INTO seen_links (link, guild_id, user_id, timestamp)
        VALUES (?, ?, ?, ?)
    """, (link, gid, uid, int(time.time())))
    db.commit()

# -----------------------------------------------------
# GBAN ENFORCEMENT ON GUILD JOIN
# -----------------------------------------------------
@client.event
async def on_guild_join(guild):
    # Save who invited the bot (uservan)
    try:
        inviter = None
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            inviter = entry.user
            break

        if inviter:
            cursor.execute("""
                INSERT OR REPLACE INTO uservan (guild_id, inviter_id, inviter_name, timestamp)
                VALUES (?, ?, ?, ?)
            """, (guild.id, inviter.id, str(inviter), int(time.time())))
            db.commit()
    except:
        pass

    # enforce GBAN
    if inviter and is_gbanned(inviter.id):
        await guild.leave()
        return

    # enforce guild ban
    if is_guild_banned(guild.id):
        await guild.leave()
        return

# -----------------------------------------------------
# READY
# -----------------------------------------------------
@client.event
async def on_ready():
    print(f"Logged in as {client.user}")

    async def periodic_cleanup():
        while True:
            await asyncio.sleep(3600 * 6)
            cutoff = int(time.time()) - 86400
            cursor.execute("DELETE FROM seen_links WHERE timestamp < ?", (cutoff,))
            db.commit()

    client.loop.create_task(periodic_cleanup())
    await tree.sync(guild=None)



# -----------------------------------------------------
# /userban + GBAN flag
# -----------------------------------------------------
@tree.command(name="user_ban", description="Ban a user")
async def user_ban_cmd(interaction: discord.Interaction, user: str, reason: str, no_appeal: bool = False, gban: bool = False):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("not owner", ephemeral=True)

    uid = int(user)
    add_user_ban(uid, reason, no_appeal, gban)

    # DM user
    try:
        u = await client.fetch_user(uid)
        await u.send(f"You were banned.\nReason: {reason}\nGlobal Ban: {gban}")
    except:
        pass

    await interaction.response.send_message(f"User {uid} banned. GBAN={gban}", ephemeral=True)


# -----------------------------------------------------
# /user_unban
# -----------------------------------------------------
@tree.command(name="user_unban", description="Unban user")
async def user_unban_cmd(interaction: discord.Interaction, user: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("nope", ephemeral=True)

    remove_user_ban(int(user))
    await interaction.response.send_message("User unbanned", ephemeral=True)
# -----------------------------------------
# main.py  (PART 2)
# continuation
# -----------------------------------------

# -----------------------------------------------------
# /guild_ban
# -----------------------------------------------------
@tree.command(name="guild_ban", description="Ban a guild")
async def guild_ban_cmd(interaction: discord.Interaction, guild_id: str, reason: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("nope", ephemeral=True)

    gid = int(guild_id)
    add_guild_ban(gid, reason)

    guild = client.get_guild(gid)
    if guild:
        try:
            await guild.leave()
        except:
            pass

    await interaction.response.send_message(
        f"Guild `{guild_id}` banned.\nReason: {reason}",
        ephemeral=True
    )


# -----------------------------------------------------
# /guild_unban
# -----------------------------------------------------
@tree.command(name="guild_unban", description="Unban a guild")
async def guild_unban_cmd(interaction: discord.Interaction, guild_id: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("nope", ephemeral=True)

    remove_guild_ban(int(guild_id))
    await interaction.response.send_message(f"Unbanned {guild_id}", ephemeral=True)


# -----------------------------------------------------
# BROADCAST (your old feature)
# With fallback: if keyword channels not found, it writes in ANY channel with perms
# -----------------------------------------------------
@tree.command(name="broadcast", description="Broadcast to all guilds")
async def broadcast_cmd(interaction: discord.Interaction, msg: str):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("nah", ephemeral=True)

    await interaction.response.send_message("Broadcast started...", ephemeral=True)

    keywords = ["general", "chat", "main"]
    sent = 0
    failed = 0

    for guild in client.guilds:
        channel = None

        # try keyword channels
        for ch in guild.text_channels:
            if any(k in ch.name.lower() for k in keywords):
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break

        # fallback — ANY writable channel
        if channel is None:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break

        if channel is None:
            failed += 1
            continue

        try:
            await channel.send(msg)
            sent += 1
        except:
            failed += 1

    await interaction.followup.send(
        f"Done.\nSent: {sent}\nFailed: {failed}"
    )


# -----------------------------------------------------
# MESSAGE SCANNER (your old link detection)
# Using SQLite to store seen links so restarts don’t wipe them
# -----------------------------------------------------
link_regex = re.compile(r"(https?://[^\s]+)")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return
    
    # check user ban
    ub = get_user_ban(message.author.id)
    if ub:
        try:
            await message.delete()
        except:
            pass
        return

    # link detection
    links = link_regex.findall(message.content)
    if not links:
        return

    for link in links:
        prev = cursor.execute(
            "SELECT * FROM seen_links WHERE link=?", (link,)
        ).fetchone()

        if prev:
            # already logged
            continue

        add_seen_link(link, message.guild.id if message.guild else 0, message.author.id)

        # your old embed formatting
        embed = discord.Embed(
            title="New Link Detected",
            description=f"**User:** {message.author} (`{message.author.id}`)\n"
                        f"**Guild:** {message.guild.name if message.guild else 'DM'} (`{message.guild.id if message.guild else 'N/A'}`)\n"
                        f"**Link:** {link}",
            color=0x00ffab
        )
        embed.set_footer(text="Logged Automatically")

        log_channel_id = os.getenv("LOG_CHANNEL")
        if log_channel_id:
            ch = client.get_channel(int(log_channel_id))
            if ch:
                await ch.send(embed=embed)


# -----------------------------------------------------
# LEAVE LOGGING (your old system)
# -----------------------------------------------------
@client.event
async def on_guild_remove(guild):
    cursor.execute(
        "INSERT INTO removed_guilds (guild_id, name, timestamp) VALUES (?, ?, ?)",
        (guild.id, guild.name, int(time.time()))
    )
    db.commit()


# -----------------------------------------------------
# /onelink  (your old “infinite loading” command)
# now fixed — it returns correctly
# -----------------------------------------------------
@tree.command(name="onelink", description="Get total unique links")
async def onelink_cmd(interaction: discord.Interaction):
    total = cursor.execute("SELECT COUNT(*) FROM seen_links").fetchone()[0]
    await interaction.response.send_message(f"Total logged links: {total}", ephemeral=True)


# -----------------------------------------------------
# /banned_users (your old request)
# -----------------------------------------------------
@tree.command(name="banned_users", description="Show all banned users")
async def banned_users_cmd(interaction: discord.Interaction):
    rows = cursor.execute("SELECT user_id, reason, gban FROM user_bans").fetchall()

    if not rows:
        return await interaction.response.send_message("none", ephemeral=True)

    msg = ""
    for u, r, g in rows:
        msg += f"**{u}** — {r} — GBAN={g}\n"

    await interaction.response.send_message(msg[:1900], ephemeral=True)


# -----------------------------------------------------
# FINAL START
# -----------------------------------------------------
client.run(TOKEN)
