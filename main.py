import sys, types, os, json, asyncio, datetime
sys.modules['audioop'] = types.ModuleType('audioop')
from flask import Flask
import discord
from discord.ext import commands, tasks
from discord import app_commands

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot alive!", 200

def run():
    port = int(os.getenv("PORT", 8080))
    print("[DEBUG] Flask keep-alive running on", port)

import threading
t = threading.Thread(target=run)
t.start()

TOKEN = os.getenv("TOKEN")

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True
INTENTS.guilds = True

# OWNERS LOCKED
OWNER_IDS = {1329161792936476683,903569932791463946}

# modlogs channel locked
MODLOG_CHANNEL_ID = 1430175693223890994

# COLORS locked
COLOR_SUCCESS = 0x00ff00
COLOR_FAIL = 0xff0000
COLOR_WARN = 0xffa500

bot = commands.Bot(command_prefix="!", intents=INTENTS)
tree = bot.tree

# storage
BANNED_FILE = "banned_guilds.json"
REMOVED_LOG = "removed_guilds.json"
BANNED_USERS_FILE = "banned_users.json"
TEMP_BANS_FILE = "tempbans.json"

maintenance_mode = False

# utils load/save json
def load_json(name):
    if not os.path.exists(name):
        with open(name,"w") as f: json.dump({},f)
    with open(name,"r") as f: return json.load(f)

def save_json(name,data):
    with open(name,"w") as f: json.dump(data,f,indent=2)

banned_groups = load_json(BANNED_FILE)
removed_logs = load_json(REMOVED_LOG)
banned_users = load_json(BANNED_USERS_FILE)
temp_bans = load_json(TEMP_BANS_FILE)

def is_owner(interaction:discord.Interaction):
    return interaction.user.id in OWNER_IDS

async def log_mod(action:str, guild:discord.Guild, moderator:discord.User, target:str|discord.User, reason:str=None):
    ch = bot.get_channel(MODLOG_CHANNEL_ID)
    if ch is None: return

    now = datetime.datetime.now().astimezone()
    rel = discord.utils.format_dt(now, style='R')
    abs = discord.utils.format_dt(now, style='F')

    e = discord.Embed(
        title="LynkX ModLogs",
        description=f"**{action}**",
        color=COLOR_WARN
    )
    e.add_field(name="Guild",value=f"{guild.name} ({guild.id})",inline=False)
    e.add_field(name="Moderator",value=f"{moderator.mention}",inline=False)
    e.add_field(name="Target",value=f"{target}",inline=False)
    e.add_field(name="Time",value=f"{abs} ({rel})",inline=False)
    if reason: e.add_field(name="Reason",value=reason,inline=False)

    await ch.send(embed=e)

@bot.event
async def on_ready():
    print("Bot Ready")
    check_tempbans.start()
    await bot.change_presence(activity=discord.Game("LynkX v2"))
# -----------------------
# PART 2 — commands + tasks
# -----------------------

import time
import aiohttp

# helpers for JSON-storage keys normalization
def ensure_str_keys(d):
    # convert integer keys to strings (if any)
    if not isinstance(d, dict):
        return {}
    return {str(k): v for k, v in d.items()}

banned_groups = ensure_str_keys(banned_groups)
banned_users = ensure_str_keys(banned_users)
temp_bans = ensure_str_keys(temp_bans)

def persist_all():
    save_json(BANNED_FILE, banned_groups)
    save_json(REMOVED_LOG, removed_logs)
    save_json(BANNED_USERS_FILE, banned_users)
    save_json(TEMP_BANS_FILE, temp_bans)

# improved modlog sender that accepts color & consistent title/footer
async def send_modlog(action: str, guild: discord.Guild | None, moderator: discord.User, target: str, color: int, reason: str | None = None):
    ch = bot.get_channel(MODLOG_CHANNEL_ID)
    if ch is None:
        # channel not available (bot might not be in the logging server or cache)
        return
    now = datetime.datetime.now().astimezone()
    rel = discord.utils.format_dt(now, style='R')
    abs_ = discord.utils.format_dt(now, style='F')

    embed = discord.Embed(
        title=action,
        description=f"{target}",
        color=color
    )
    # Add fields in a consistent order
    if guild:
        embed.add_field(name="Guild", value=f"{guild.name} (`{guild.id}`)", inline=False)
    else:
        embed.add_field(name="Guild", value="(private / DMs) or unknown", inline=False)

    embed.add_field(name="Moderator", value=f"{moderator} (`{moderator.id}`)", inline=False)
    embed.add_field(name="Target", value=f"{target}", inline=False)
    embed.add_field(name="Time", value=f"{abs_}  |  {rel}", inline=False)
    if reason:
        embed.add_field(name="Reason", value=reason, inline=False)

    embed.set_footer(text="LynkX ModLogs")
    await ch.send(embed=embed)

# Owner-check decorator for app_commands that returns friendly ephemeral message
def owner_only_check():
    async def pred(interaction: discord.Interaction):
        if interaction.user.id not in OWNER_IDS:
            try:
                await interaction.response.send_message("❌ You are not allowed to run this command.", ephemeral=True)
            except Exception:
                # If response already used, attempt followup
                try:
                    await interaction.followup.send("❌ You are not allowed to run this command.", ephemeral=True)
                except Exception:
                    pass
            return False
        return True
    return app_commands.check(pred)

# -----------------------
# Roblox fetching utility (used by /links)
# -----------------------
async def fetch_group_posts():
    if not GROUP_ID:
        return []
    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"} if ROBLOX_COOKIE else {}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=15) as resp:
                if resp.status != 200:
                    print(f"[Roblox] fetch failed: {resp.status}")
                    return []
                data = await resp.json()
    except Exception as e:
        print("[Roblox] fetch error:", e)
        return []

    links = []
    for post in data.get("data", []):
        content = post.get("body", "") or ""
        found = re.findall(r"(https?://[^\s]*roblox\.com/[^\s]*)", content, flags=re.IGNORECASE)
        links.extend(found)

    # dedupe but preserve order
    seen = set()
    out = []
    for l in links:
        if l not in seen:
            seen.add(l)
            out.append(l)
    return out

# -----------------------
# check_user_ban wrapper for commands
# -----------------------
def is_tempbanned_user(uid: int):
    s = str(uid)
    entry = temp_bans.get(s)
    if not entry:
        return False
    expires = entry.get("expires", 0)
    now = time.time()
    if expires <= now:
        # expired — cleanup
        temp_bans.pop(s, None)
        save_json(TEMP_BANS_FILE, temp_bans)
        return False
    return True

async def check_user_ban_cmd(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    if uid in banned_users:
        await interaction.response.send_message("Error ⚠️: User is permanently banned from using this program ❌ | DM h.aze.l to appeal.", ephemeral=True)
        return True
    if is_tempbanned_user(int(uid)):
        entry = temp_bans.get(uid)
        exp_ts = int(entry.get("expires"))
        # show both F + R (user-localized by Discord)
        await interaction.response.send_message(f"Error ⚠️: User is temporarily banned until <t:{exp_ts}:F>  |  <t:{exp_ts}:R> ❌ | DM h.aze.l to appeal.", ephemeral=True)
        return True
    return False

# -----------------------
# slash commands
# -----------------------

# /links (public)
@tree.command(name="links", description="Get scammer private server links 🔗⚠️")
async def links_command(interaction: discord.Interaction):
    # guild ban check
    gid_str = str(interaction.guild.id) if interaction.guild else None
    if gid_str and gid_str in banned_groups:
        embed = discord.Embed(title="Access Denied ❌️", description="ℹ️ This bot is no longer associated with this server.", color=COLOR_FAIL)
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return

    # user ban check (perm or temp)
    if await check_user_ban_cmd(interaction):
        return

    await interaction.response.defer(thinking=True)

    links = await fetch_group_posts()
    if not links:
        # chosen tone B
        await interaction.followup.send("No links found. Try again later.")
        return

    message = "\n".join(links[:10])
    if maintenance_mode:
        maint_embed = discord.Embed(
            title="⚠️ Maintenance Mode Active 🟠",
            description="The bot may experience temporary issues while we perform maintenance.\n\n" + message,
            color=COLOR_WARN
        )
        maint_embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
        await interaction.followup.send(embed=maint_embed)
        return

    embed = discord.Embed(title="Latest SAB Scammer Links 🔗⚠️", description=message, color=0x00ffcc)
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Owner-only commands ----
# Use owner_only_check to return ephemeral denial instead of CheckFailure

# /ban_user
@tree.command(name="ban_user", description="Ban a user (owner-only)")
@owner_only_check()
@app_commands.describe(user_id="Numeric user ID to ban permanently")
async def ban_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = str(int(user_id))
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    if uid in banned_users:
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return

    # remove any tempban if present (manual permanent ban supersedes)
    if uid in temp_bans:
        temp_bans.pop(uid, None)
        save_json(TEMP_BANS_FILE, temp_bans)

    banned_users[uid] = True
    save_json(BANNED_USERS_FILE, banned_users)

    await interaction.response.send_message(f"✅ User `{uid}` permanently banned.", ephemeral=True)
    # log — red for permanent ban
    await send_modlog("Permanent Ban Issued", interaction.guild, interaction.user, f"User `{uid}`", color=COLOR_FAIL)

# /unban_user (handles both perm and temp)
@tree.command(name="unban_user", description="Unban a user (owner-only)")
@owner_only_check()
@app_commands.describe(user_id="Numeric user ID to unban")
async def unban_user(interaction: discord.Interaction, user_id: str):
    try:
        uid = str(int(user_id))
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    removed = False
    if uid in banned_users:
        banned_users.pop(uid, None)
        save_json(BANNED_USERS_FILE, banned_users)
        removed = True

    if uid in temp_bans:
        temp_bans.pop(uid, None)
        save_json(TEMP_BANS_FILE, temp_bans)
        removed = True

    if removed:
        await interaction.response.send_message(f"✅ User `{uid}` has been unbanned.", ephemeral=True)
        # green for unban
        await send_modlog("Unban Issued", interaction.guild, interaction.user, f"User `{uid}`", color=COLOR_SUCCESS)
    else:
        await interaction.response.send_message("⚠️ User was not banned.", ephemeral=True)

# /tempban (minutes)
@tree.command(name="tempban", description="Temporarily ban a user (owner-only)")
@owner_only_check()
@app_commands.describe(user_id="User ID to tempban", duration_minutes="Duration in minutes")
async def tempban_cmd(interaction: discord.Interaction, user_id: str, duration_minutes: int):
    try:
        uid = str(int(user_id))
    except:
        await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
        return

    if uid in banned_users or is_tempbanned_user(int(uid)):
        await interaction.response.send_message("⚠️ User already banned.", ephemeral=True)
        return

    now_ts = int(time.time())
    expires = now_ts + max(1, int(duration_minutes)) * 60
    temp_bans[uid] = {"expires": expires, "timestamp": now_ts}
    save_json(TEMP_BANS_FILE, temp_bans)

    # reply with human-friendly expiry (both F and R will localize for viewer)
    await interaction.response.send_message(f"✅ User `{uid}` temporarily banned until <t:{expires}:F>  |  <t:{expires}:R>.", ephemeral=True)
    # orange for temporary ban
    await send_modlog("Temporary Ban Issued", interaction.guild, interaction.user, f"User `{uid}` — until <t:{expires}:F>  |  <t:{expires}:R>", color=COLOR_WARN)

# /ban_guild (owner-only) - finalizes earlier partial in part1
@tree.command(name="ban_guild", description="Ban server (owner only)")
@owner_only_check()
@app_commands.describe(guild_id="Guild ID to ban")
async def ban_guild_cmd_final(interaction: discord.Interaction, guild_id: str):
    gid = str(guild_id)
    if gid in banned_groups:
        await interaction.response.send_message("Already banned.", ephemeral=True)
        return
    banned_groups[gid] = True
    save_json(BANNED_FILE, banned_groups)
    await interaction.response.send_message("✅ Guild banned permanently.", ephemeral=True)
    # log mod action (red)
    await send_modlog("Server Permanent Ban Issued", interaction.guild, interaction.user, f"Guild `{gid}`", color=COLOR_FAIL)

# /unban_guild
@tree.command(name="unban_guild", description="Unban server (owner-only)")
@owner_only_check()
@app_commands.describe(guild_id="Guild ID to unban")
async def unban_guild_cmd(interaction: discord.Interaction, guild_id: str):
    gid = str(guild_id)
    if gid not in banned_groups:
        await interaction.response.send_message("⚠️ Guild not in banned list.", ephemeral=True)
        return
    banned_groups.pop(gid, None)
    save_json(BANNED_FILE, banned_groups)
    await interaction.response.send_message("✅ Guild unbanned.", ephemeral=True)
    await send_modlog("Server Unban Issued", interaction.guild, interaction.user, f"Guild `{gid}`", color=COLOR_SUCCESS)

# /ban_invite - resolve invite then ban guild id
@tree.command(name="ban_invite", description="Ban a guild by invite (owner-only)")
@owner_only_check()
@app_commands.describe(invite="Invite code or full invite URL")
async def ban_invite_cmd(interaction: discord.Interaction, invite: str):
    m = re.search(r"(?:discord\.gg/|discordapp\.com/invite/)?([A-Za-z0-9\-]+)$", invite.strip())
    if not m:
        await interaction.response.send_message("❌ Could not parse invite.", ephemeral=True)
        return
    code = m.group(1)
    url = f"https://discord.com/api/v10/invites/{code}?with_counts=false"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status != 200:
                    await interaction.response.send_message(f"❌ Failed to resolve invite (HTTP {resp.status}).", ephemeral=True)
                    return
                data = await resp.json()
    except Exception as e:
        await interaction.response.send_message("❌ Failed to resolve invite.", ephemeral=True)
        return

    guild = data.get("guild")
    if not guild:
        await interaction.response.send_message("❌ Invite resolved but no guild info.", ephemeral=True)
        return
    gid = str(guild.get("id"))
    name = guild.get("name", "Unknown")
    if gid in banned_groups:
        await interaction.response.send_message(f"⚠️ Guild **{name}** already banned.", ephemeral=True)
        return
    banned_groups[gid] = True
    save_json(BANNED_FILE, banned_groups)
    await interaction.response.send_message(f"✅ Guild **{name}** (`{gid}`) has been banned.", ephemeral=True)
    await send_modlog("Server Permanent Ban Issued", interaction.guild, interaction.user, f"Guild **{name}** (`{gid}`)", color=COLOR_FAIL)

# /list_banned
@tree.command(name="list_banned", description="List banned guilds (owner-only)")
@owner_only_check()
async def list_banned_cmd(interaction: discord.Interaction):
    if not banned_groups:
        await interaction.response.send_message("No banned guilds.", ephemeral=True)
        return
    lines = []
    for i, gid in enumerate(banned_groups.keys(), start=1):
        try:
            gobj = bot.get_guild(int(gid))
            name = gobj.name if gobj else "Not in guild"
        except Exception:
            name = "Not in guild"
        lines.append(f"{i}. {name} | {gid}")
    text = "\n".join(lines)
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Banned guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "banned_guilds.txt"), ephemeral=True)

# /list_removed
@tree.command(name="list_removed", description="List removed guilds (owner-only)")
@owner_only_check()
async def list_removed_cmd(interaction: discord.Interaction):
    if not removed_logs:
        await interaction.response.send_message("No recorded removed guilds.", ephemeral=True)
        return
    lines = [f"{i+1}. {e.get('name','Unknown')} | {e.get('id','Unknown')}" for i, e in enumerate(removed_logs)]
    text = "\n".join(lines)
    if len(text) <= 1800:
        await interaction.response.send_message(f"**Removed guilds:**\n{text}", ephemeral=True)
    else:
        bio = io.StringIO(text)
        bio.seek(0)
        await interaction.response.send_message(file=discord.File(bio, "removed_guilds.txt"), ephemeral=True)

# /maintenance toggle
@tree.command(name="maintenance", description="Toggle maintenance mode (owner-only)")
@owner_only_check()
@app_commands.describe(enable="Enable or disable maintenance mode")
async def maintenance_cmd(interaction: discord.Interaction, enable: bool):
    global maintenance_mode
    maintenance_mode = bool(enable)
    await interaction.response.send_message(f"Maintenance mode {'ENABLED 🟠' if maintenance_mode else 'DISABLED ✅'}.", ephemeral=True)
    # log the maintenance toggle as requested (user wanted B = log everything)
    await send_modlog("Maintenance Toggled", interaction.guild, interaction.user, f"Maintenance set to {maintenance_mode}", color=COLOR_WARN)

# -----------------------
# background task: auto-unban expired tempbans
# -----------------------
@tasks.loop(seconds=60.0)
async def check_tempbans():
    now = int(time.time())
    removed = []
    for uid, entry in list(temp_bans.items()):
        try:
            expires = int(entry.get("expires", 0))
        except:
            expires = 0
        if expires <= now:
            # auto-unban cleanup
            temp_bans.pop(uid, None)
            save_json(TEMP_BANS_FILE, temp_bans)
            removed.append(uid)
            # log auto-unban (green)
            # no moderator (system)
            await send_modlog("Temporary Ban Expired (Auto Unban)", None, bot.user, f"User `{uid}`", color=COLOR_SUCCESS)
    # persist if any changes
    if removed:
        save_json(TEMP_BANS_FILE, temp_bans)

# -----------------------
# events: track removed guilds
# -----------------------
@bot.event
async def on_guild_remove(guild):
    # log removal to removed_logs list for future inspection
    try:
        entry = {"id": guild.id, "name": guild.name, "timestamp": int(time.time())}
        # if removed_logs is dict-like convert to list style append
        if isinstance(removed_logs, dict):
            # convert to list in-place if it was mistakenly a dict
            new = []
            for k,v in removed_logs.items():
                new.append(v)
            removed_logs.clear()
            removed_logs.extend(new)
        removed_logs.append(entry)
        save_json(REMOVED_LOG, removed_logs)
    except Exception as e:
        print("on_guild_remove log error:", e)

# -----------------------
# startup sync helper (sync commands after ready)
# -----------------------
async def _sync_commands_once():
    await bot.wait_until_ready()
    try:
        await tree.sync()
        print("Slash commands synced.")
    except Exception as e:
        print("Command sync failed:", e)

bot.loop.create_task(_sync_commands_once())

# -----------------------
# run the bot
# -----------------------
if __name__ == "__main__":
    # start tempban loop only when bot is running
    try:
        check_tempbans.start()
    except RuntimeError:
        # already started
        pass

    # finally run bot
    token = TOKEN or os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
    if not token:
        print("Missing bot token in env. Set DISCORD_TOKEN or TOKEN.")
        sys.exit(1)
    bot.run(token)
