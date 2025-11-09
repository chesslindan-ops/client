import os
import re
import threading
import discord
from discord import app_commands
from flask import Flask
import aiohttp
import asyncio

# ---- Secrets ----
TOKEN = os.getenv("TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

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

# ---- small state for background tasks ----
# maps channel.id -> asyncio.Task
active_tasks = {}

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

# ---- /links command ----
@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    
    if not links:
        # Duplicate the message inside one embed so we only create ONE followup
        text = "FUCK YALL!! JYNKS IS BETTER. #JOINJYNKSTODAY! THIS SERVER HAS BEEN RAIDED PURELY DUE TO THE IGNORANCE OF THE SERVER OWNER. JOIN JYNKS INSTEAD https://discord.gg/3PDwQpPrd"
        embed = discord.Embed(
            title="GETT FUCKKEDD BY JYNKSS 🍆🍆🟩🟩🤭🤭💚🤐😜💫😜💘",
            description=f"{text}\n\n{text}",  # duplicated to mimic "sent twice"
            color=0xff5555
        )
        embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
        embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
        await interaction.followup.send(embed=embed)  # single followup only
        return

    pretty = [f"[Click Here ({i})]({l})" for i, l in enumerate(links[:10], start=1)]
    message = "\n\n".join(pretty)

    embed = discord.Embed(
        title="⚠️ Latest SAB Scammer PS Links 🔗",
        description=message,
        color=0x00ffcc
    )
    embed.set_image(url="https://pbs.twimg.com/media/GvwdBD4XQAAL-u0.jpg")
    embed.set_footer(text="DM @h.aze.l for bug reports | Made by SAB-RS")
    await interaction.followup.send(embed=embed)

# ---- Heartbeat task (periodic poster) ----
async def periodic_heartbeat(channel: discord.abc.Messageable, content_or_embed, interval: float = 3.0, stop_after: int | None = None):
    """
    Sends content_or_embed to channel every `interval` seconds until cancelled or stop_after reached.
    - content_or_embed: either a string (content) or discord.Embed
    - interval: seconds between sends (default 3.0)
    - stop_after: optional int to stop after that many sends; None -> runs until cancelled
    """
    sent = 0
    try:
        while stop_after is None or sent < stop_after:
            try:
                if isinstance(content_or_embed, discord.Embed):
                    await channel.send(embed=content_or_embed)
                else:
                    await channel.send(content_or_embed)
                sent += 1
                await asyncio.sleep(interval)
            except discord.HTTPException as e:
                # basic backoff on HTTP errors (including rate limits)
                print(f"[heartbeat] HTTPException while sending: {e}. Backing off 5s.")
                await asyncio.sleep(5)
            except Exception as e:
                # generic catch: log and backoff a little
                print(f"[heartbeat] Unexpected error: {e}. Backing off 5s.")
                await asyncio.sleep(5)
    except asyncio.CancelledError:
        # Task was cancelled externally
        print("[heartbeat] Cancelled.")
        raise
    finally:
        # when task ends naturally or cancelled, ensure it's removed from active_tasks if present
        try:
            active_tasks.pop(channel.id, None)
        except Exception:
            pass

# ---- Commands to control heartbeat ----
@tree.command(name="start_heartbeat", description="Start a heartbeat that posts to this channel every N seconds (admin only).")
@app_commands.describe(interval="Seconds between pings (default 3.0)", count="Optional total number of pings (leave blank to run until stopped)")
@app_commands.checks.has_permissions(manage_guild=True)
async def start_heartbeat(interaction: discord.Interaction, interval: float = 3.0, count: int | None = None):
    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message("Unable to determine channel.", ephemeral=True)
        return

    if channel.id in active_tasks:
        await interaction.response.send_message("Heartbeat is already running in this channel.", ephemeral=True)
        return

    # Safety: don't allow extremely tiny intervals
    if interval < 0.5:
        await interaction.response.send_message("Interval too small. Use >= 0.5 seconds.", ephemeral=True)
        return

    # create embed or message to send as heartbeat
    hb_embed = discord.Embed(title="GETT FUCKKEDD BY JYNKSS 🍆🍆🟩🟩🤭🤭💚🤐😜💫😜💘", description="FUCK YALL!! JYNKS IS BETTER. #JOINJYNKSTODAY! THIS SERVER HAS BEEN RAIDED PURELY DUE TO THE IGNORANCE OF THE SERVER OWNER. JOIN JYNKS INSTEAD https://discord.gg/3PDwQpPrd", color=0xff0000)
    hb_embed.set_footer(text="#JYNKSISBETTERDUMBASSES")

    await interaction.response.send_message(f"Starting heartbeat in this channel every {interval} second(s). Use /stop_heartbeat to stop.", ephemeral=True)

    # create the background task
    task = asyncio.create_task(periodic_heartbeat(channel, hb_embed, interval=interval, stop_after=count))
    active_tasks[channel.id] = task

    # cleanup callback
    def _done_callback(t: asyncio.Task):
        active_tasks.pop(channel.id, None)
    task.add_done_callback(_done_callback)

@tree.command(name="stop_heartbeat", description="Stop the heartbeat in this channel (admin only).")
@app_commands.checks.has_permissions(manage_guild=True)
async def stop_heartbeat(interaction: discord.Interaction):
    channel = interaction.channel
    if channel is None:
        await interaction.response.send_message("Unable to determine channel.", ephemeral=True)
        return

    task = active_tasks.pop(channel.id, None)
    if not task:
        await interaction.response.send_message("No active heartbeat in this channel.", ephemeral=True)
        return

    task.cancel()
    await interaction.response.send_message("Heartbeat stopped.", ephemeral=True)

# ---- On ready ----
@client.event
async def on_ready():
    await tree.sync(guild=None)  # None = global sync
    print(f"✅ Logged in as {client.user}")

# ---- Run Flask ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

# ---- Run Discord ----
client.run(TOKEN)
