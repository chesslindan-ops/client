# Lal.py - Full file (final integrated)

import os
import re
import threading
import json
import discord
from discord import app_commands
from flask import Flask
import aiohttp
import asyncio

# ---- Config / Secrets ----
TOKEN = os.getenv("TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# ---- Blacklist persistent file path (repo relative) ----
BLACKLIST_FILE = "data/blacklist.json"
OWNER_ID = 1436706708830421085
BOT_NAME = "JynkS"
BLOCK_MSG = "❌️ You are blacklisted from using JynkS. DM @jynks_b to appeal | 429"

# ---- Discord setup ----
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ---- Ensure blacklist file exists / load / save ----
def ensure_blacklist_file():
    folder = os.path.dirname(BLACKLIST_FILE)
    if folder and not os.path.exists(folder):
        os.makedirs(folder, exist_ok=True)
    if not os.path.exists(BLACKLIST_FILE):
        with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
            json.dump({"blacklisted": [], "seed": ["www.china.com"]}, f)

def load_blacklist():
    ensure_blacklist_file()
    try:
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(x) for x in data.get("blacklisted", [])}
    except Exception:
        return set()

def save_blacklist(blackset):
    ensure_blacklist_file()
    try:
        with open(BLACKLIST_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"blacklisted": [], "seed": ["www.china.com"]}
    data["blacklisted"] = sorted(list(blackset))
    with open(BLACKLIST_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

# in-memory cache
blacklisted = load_blacklist()

# ---- Flask keep alive ----
app = Flask(__name__)

@app.route("/")
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    print(f"[DEBUG] Flask running on port {port}")
    app.run(host="0.0.0.0", port=port)

# ---- Fetch group posts (original logic preserved) ----
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

# ---- Global blacklist check ----
async def global_blacklist_check(interaction: discord.Interaction) -> bool:
    # owner bypass
    if interaction.user and interaction.user.id == OWNER_ID:
        return True

    current = load_blacklist()
    if interaction.user and interaction.user.id in current:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(BLOCK_MSG, ephemeral=True)
            else:
                await interaction.followup.send(BLOCK_MSG, ephemeral=True)
        except Exception as e:
            print(f"[WARN] Failed to notify blacklisted user: {e}")
        raise app_commands.CheckFailure("user is blacklisted")
    return True

# register the global check BEFORE defining any slash commands
tree.add_check(global_blacklist_check)

# ---- Blacklist management cmds (Owner only) ----
@tree.command(name="bl", description="Blacklist a user from using JynkS")
async def blacklist_user(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("no perms", ephemeral=True)

    current = load_blacklist()
    current.add(user.id)
    save_blacklist(current)
    # update in-memory cache
    global blacklisted
    blacklisted = current
    await interaction.response.send_message(f"{user.id} added to blacklist | permanent.", ephemeral=True)


@tree.command(name="ubl", description="Unblacklist a user from using JynkS")
async def unblacklist_user(interaction: discord.Interaction, user: discord.User):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("no perms", ephemeral=True)

    current = load_blacklist()
    if user.id in current:
        current.remove(user.id)
        save_blacklist(current)
        # update in-memory cache
        global blacklisted
        blacklisted = current
        return await interaction.response.send_message(f"{user.id} removed from blacklist.", ephemeral=True)
    else:
        return await interaction.response.send_message("that id is not blacklisted.", ephemeral=True)


@tree.command(name="reloadtree", description="Sync slash cmds to discord")
async def reload_tree(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        return await interaction.response.send_message("no perms", ephemeral=True)

    await tree.sync()
    await interaction.response.send_message("synced ✅", ephemeral=True)

# ---- /raid command (uses current channel, burst 5 messages with 0.3s gap) ----
@tree.command(name="raid", description="Mwahahahha")
async def raid_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    # (global check will have already blocked blacklisted users)
    links = await fetch_group_posts()

    if not links:
        text = "FUCK YALL!! JYNKS IS BETTER. #JOINJYNKSTODAY! THIS SERVER HAS BEEN RAIDED PURELY DUE TO THE IGNORANCE OF THE SERVER OWNER. NIGGA REALLY THOUGHT HE COULD RAID A BOT DEVELOPERS SERVER LOLLLL"
        embedr = discord.Embed(
            title="GETT FUCKKEDD BY JYNKSS 🍆🍆🟩🟩🤭🤭💚🤐😜💫😜💘",
            description=f"{text}\n\n{text}",
            color=0xff5555
        )
        embedr.set_footer(text="REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD")
        embedr.set_image(url="https://media.tenor.com/vkIBLYGz5O0AAAAM/im-going-to-send-nsfw-in-ur-dms.gif")
        embedr.set_thumbnail(url="https://media.tenor.com/8YQU67-dvTUAAAAM/penis.gif")
        # burst 5 sends with tiny delay
        for _ in range(5):
            await asyncio.sleep(0.3)
            await interaction.followup.send(embed=embedr)
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

    # burst 5 sends with tiny delay
    for _ in range(5):
        await asyncio.sleep(0.3)
        await interaction.followup.send(embed=embed)


# ---- /kaisen command (different embed content; uses current channel; burst 5) ----
@tree.command(name="kaisen", description="Custom RaidMode for Muslim")
async def kaisen_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)

    links = await fetch_group_posts()

    if not links:
        text = "JUJUTSU KAISEN IS THE BEST ❤️❤️❤️"
        embedJ = discord.Embed(
            title="Yuji Itadori and Gojo",
            description=f"{text}\n\n{text}",
            color=0x0000ff
        )
        embedJ.set_footer(text="W Gojo ❤️‍🩹")
        embedJ.set_image(url="https://gifdb.com/images/high/jujutsu-kaisen-gojo-sukuna-fight-72a8dzhaor1a45vq.webp")
        embedJ.set_thumbnail(url="https://media.tenor.com/UVe_VIz4vPcAAAAM/jjk-jujutsu-kaisen.gif")
        for _ in range(5):
            await asyncio.sleep(0.3)
            await interaction.followup.send(embed=embedJ)
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

    for _ in range(5):
        await asyncio.sleep(0.3)
        await interaction.followup.send(embed=embed)

# ---- On ready ----
@client.event
async def on_ready():
    # sync globally (may take a minute to appear)
    await tree.sync(guild=None)
    print(f"✅ Logged in as {client.user}")

# ---- Run Flask thread and Discord client ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()

client.run(TOKEN)
