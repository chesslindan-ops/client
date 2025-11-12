# main.py - PART 1/3
import os
import re
import threading
import json
import io
import time
import asyncio
import discord
from discord import app_commands
from flask import Flask
import aiohttp
from discord.ui import View, Button

# ---- Config / Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")
OWNER_ID = int(os.getenv("OWNER_ID", "1329161792936476683"))

# ---- Files ----
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"
INVITE_CACHE_FILE = "invite_cache.json"

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

# ---- in-memory state ----
BANNED_GUILDS = load_json(BANNED_FILE, [])
REMOVED_GUILDS = load_json(REMOVED_LOG, [])
BANNED_USERS = load_json(BANNED_USERS_FILE, [])
TEMP_BANS = load_json(TEMP_BANS_FILE, [])
INVITE_CACHE = load_json(INVITE_CACHE_FILE, {})

def save_tempbans():
    save_json(TEMP_BANS_FILE, TEMP_BANS)

def save_invite_cache():
    save_json(INVITE_CACHE_FILE, INVITE_CACHE)

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
intents.members = True  # needed if you rely on member_count or member objects
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

MAINTENANCE = False
# main.py - PART 2/3

# ---- small helpers ----
def to_int(val):
    try:
        return int(val)
    except Exception:
        return None

def find_banned_user_entry(uid: int):
    for entry in BANNED_USERS:
        if isinstance(entry, dict) and entry.get("id") == uid:
            return entry
        if not isinstance(entry, dict) and entry == uid:
            return {"id": uid, "reason": "No reason recorded", "timestamp": None}
    return None

def find_banned_guild_entry(gid: int):
    for entry in BANNED_GUILDS:
        if isinstance(entry, dict) and entry.get("id") == gid:
            return entry
        if not isinstance(entry, dict) and entry == gid:
            return {"id": gid, "name": None, "reason": "No reason recorded", "timestamp": None}
    return None

def is_tempbanned_entry(uid: int):
    now = time.time()
    removed = False
    for entry in TEMP_BANS[:]:
        if entry.get("expires", 0) <= now:
            TEMP_BANS.remove(entry)
            removed = True
    if removed:
        save_tempbans()
    for entry in TEMP_BANS:
        if entry.get("id") == uid:
            return entry
    return None

# ---- global blacklist check (applies to all commands) ----
@tree.check
async def global_blacklist_check(interaction: discord.Interaction):
    # user ban check
    uid = interaction.user.id
    uentry = find_banned_user_entry(uid)
    if uentry:
        reason = uentry.get("reason", "No reason provided")
        ts = uentry.get("timestamp")
        ts_text = f"\nBanned at: <t:{int(ts)}:F>" if ts else ""
        embed = discord.Embed(
            title="🚫 You are banned from this bot",
            description=f"**Reason:** {reason}{ts_text}\nIf you think this is a mistake, contact the owner.",
            color=discord.Color.red()
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            # If response already sent, attempt followup
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                pass
        return False

    # tempban check
    tentry = is_tempbanned_entry(uid)
    if tentry:
        reason = tentry.get("reason", "No reason provided")
        expires = int(tentry.get("expires", time.time()))
        embed = discord.Embed(
            title="⏳ You are temporarily banned",
            description=f"**Reason:** {reason}\nExpires: <t:{expires}:F>",
            color=discord.Color.orange()
        )
        try:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            try:
                await interaction.followup.send(embed=embed, ephemeral=True)
            except:
                pass
        return False

    # guild ban check
    gid = interaction.guild_id
    if gid:
        gentry = find_banned_guild_entry(gid)
        if gentry:
            reason = gentry.get("reason", "No reason provided")
            name = gentry.get("name") or (interaction.guild.name if interaction.guild else "Unknown")
            ts = gentry.get("timestamp")
            ts_text = f"\nBanned at: <t:{int(ts)}:F>" if ts else ""
            embed = discord.Embed(
                title="❌ This server is blacklisted",
                description=f"**Server:** {name}\n**Reason:** {reason}{ts_text}\nContact the owner to appeal.",
                color=discord.Color.red()
            )
            try:
                await interaction.response.send_message(embed=embed, ephemeral=True)
            except Exception:
                try:
                    await interaction.followup.send(embed=embed, ephemeral=True)
                except:
                    pass
            return False

    # allow command
    return True

# ---- owner_only decorator ----
def owner_only():
    def predicate(interaction: discord.Interaction):
        return interaction.user.id == OWNER_ID
    return app_commands.check(predicate)

# ---- Roblox group wall fetcher ----
async def fetch_group_posts():
    if not GROUP_ID:
        return []
    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"} if ROBLOX_COOKIE else {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    print(f"[WARN] fetch_group_posts HTTP {resp.status}")
                    return []
                data = await resp.json()
    except Exception as e:
        print(f"[ERROR] fetch_group_posts: {e}")
        return []
    links = []
    for post in data.get("data", []):
        content = post.get("body", "")
        found = re.findall(r"(https?://[^\s]+roblox\.com/[^\s]*)", content)
        links.extend(found)
    # dedupe preserving order
    seen = set()
    unique = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    return unique

# ---- Invite resolver with caching and basic 429 handling ----
async def resolve_invite_code(code: str):
    # normalize
    code = code.strip()
    if code in INVITE_CACHE:
        return INVITE_CACHE[code]
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 429:
                    # rate-limited: try reading retry_after then raise to caller
                    try:
                        data = await resp.json()
                        retry = data.get("retry_after", 5)
                    except:
                        retry = 5
                    raise RuntimeError(f"RATE_LIMITED:{retry}")
                if resp.status != 200:
                    raise RuntimeError(f"HTTP_{resp.status}")
                data = await resp.json()
                INVITE_CACHE[code] = data
                save_invite_cache()
                return data
    except Exception as e:
        raise
# main.py - PART 3/3

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢", ephemeral=True)
        return
    pretty = [f"[Click Here ({i})]({l})" for i, l in enumerate(links[:10], start=1)]
    message = "\n\n".join(pretty)
    title = "⚠️ Latest SAB Scammer PS Links 🔗"
    if MAINTENANCE:
        title = "⚠️ Maintenance Mode 🟠 | Latest SAB Scammer Links 🔗"
        message = f"⚠️ The bot is currently in maintenance mode and may experience issues.\n\n{message}"
    embed = discord.Embed(title=title, description=message, color=0x00ffcc if not MAINTENANCE else 0xFFA500)
    embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- /onelink command ----
@tree.command(name="onelink", description="Get the first scammer private server link with a button")
async def onelink_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢", ephemeral=True)
        return
    first_link = links[0]
    view = View()
    color = 0x00ffcc if not MAINTENANCE else 0xFFA500
    embed = discord.Embed(title="❌️ FATAL ERROR. GUILDSTATUS==2 (Suspension)", description="Service temporarily suspended by developer until a resolution is found. Apologies for all inconvenience caused.", color=color)
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed, view=view)

# ---- User ban commands ----
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only()
@app_commands.describe(user_id="User ID to ban", reason="Reason for ban")
async def ban_user(interaction: discord.Interaction, user_id: str, reason: str):
    uid = to_int(user_id)
    if not uid:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return
    if find_banned_user_entry(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    entry = {"id": uid, "reason": reason, "timestamp": time.time()}
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
    # also remove tempbans
    for t in TEMP_BANS[:]:
        if t.get("id") == uid:
            TEMP_BANS.remove(t)
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
    if find_banned_user_entry(uid) or is_tempbanned_entry(uid):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return
    expires_at = time.time() + max(1, duration_minutes) * 60
    TEMP_BANS.append({"id": uid, "expires": expires_at, "reason": reason})
    save_tempbans()
    await interaction.response.send_message(f"✅ User `{uid}` tempbanned for {duration_minutes} minutes.\n**Reason:** {reason}", ephemeral=True)

# ---- Guild bans / invite ----
@tree.command(name="ban_guild", description="Ban a guild (owner-only)")
@owner_only()
@app_commands.describe(guild_id="Guild ID to ban", reason="Reason for guild ban")
async def ban_guild(interaction: discord.Interaction, guild_id: str, reason: str):
    gid = to_int(guild_id)
    if not gid:
        await interaction.response.send_message("❌ Invalid guild ID.", ephemeral=True)
        return
    if find_banned_guild_entry(gid):
        await interaction.response.send_message("⚠️ Guild already banned.", ephemeral=True)
        return
    g = client.get_guild(gid)
    name = g.name if g else None
    entry = {"id": gid, "name": name, "reason": reason, "timestamp": time.time()}
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
@app_commands.describe(invite="Invite code or URL", reason="Reason for ban")
async def ban_invite(interaction: discord.Interaction, invite: str, reason: str):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/|https?://discord.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("❌ Could not parse invite.", ephemeral=True)
        return
    code = m.group(1)
    try:
        data = await resolve_invite_code(code)
    except RuntimeError as e:
        s = str(e)
        if s.startswith("RATE_LIMITED:"):
            retry = float(s.split(":",1)[1])
            await interaction.response.send_message(f"⚠️ Rate-limited by Discord. Retry after {retry:.1f}s", ephemeral=True)
            return
        elif s.startswith("HTTP_"):
            await interaction.response.send_message(f"❌ Failed to resolve invite ({s}).", ephemeral=True)
            return
        else:
            await interaction.response.send_message(f"❌ Error resolving invite: {e}", ephemeral=True)
            return
    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("❌ Invite returned no guild info.", ephemeral=True)
        return
    gid = int(guild["id"])
    name = guild.get("name", "Unknown")
    if find_banned_guild_entry(gid):
        await interaction.response.send_message(f"⚠️ Guild **{name}** already banned.", ephemeral=True)
        return
    BANNED_GUILDS.append({"id": gid, "name": name, "reason": reason, "timestamp": time.time()})
    save_json(BANNED_FILE, BANNED_GUILDS)
    await interaction.response.send_message(f"✅ Guild **{name}** banned.\n**Reason:** {reason}", ephemeral=True)

# ---- Listing commands ----
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
            name = client.get_guild(gid).name if client.get_guild(gid) else "Unknown"
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
            ts_text = f" | Banned at: <t:{int(ts)}:F>" if ts else ""
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

# ---- Announce global ----
@tree.command(name="announce", description="Send a global announcement (owner-only)")
@owner_only()
@app_commands.describe(message="Message to announce globally (multi-line allowed)")
async def announce(interaction: discord.Interaction, message: str):
    embed = discord.Embed(title="Global Announcement From Developer", description=message, color=0x0000ff)
    sent_count = 0
    for guild in client.guilds:
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                try:
                    await channel.send(embed=embed)
                    sent_count += 1
                except:
                    pass
                break
    await interaction.response.send_message(f"✅ Announcement sent to {sent_count} guilds.", ephemeral=True)

# ---- Maintenance toggle ----
@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
@owner_only()
@app_commands.describe(state="on/off")
async def maintenance_cmd(interaction: discord.Interaction, state: str):
    s = state.lower()
    if s not in ["on", "off"]:
        await interaction.response.send_message("use: /maintenance on  |  /maintenance off", ephemeral=True)
        return
    global MAINTENANCE
    MAINTENANCE = (s == "on")
    await interaction.response.send_message(f"maintenance set to **{s}**", ephemeral=True)

# ---- Sync ----
@tree.command(name="update_tree", description="Sync slash commands (owner-only)")
@owner_only()
async def update_tree(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await tree.sync()
        await interaction.followup.send(f"✅ Commands tree synced! Total commands: {len(synced)}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to sync commands tree: {e}", ephemeral=True)

# ---- Events ----
@client.event
async def on_ready():
    try:
        await tree.sync()
    except Exception as e:
        print(f"[WARN] sync failed on_ready: {e}")
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

# ---- Run ----
if __name__ == "__main__":
    # start flask in background
    threading.Thread(target=run_flask, daemon=True).start()
    client.run(TOKEN)
