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
@tree.command(name="raid", description="Mwahahahha")
async def links_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    
    if not links:
        # Duplicate the message inside one embed so we only create ONE followup
        text = "FUCK YALL!! JYNKS IS BETTER. #JOINJYNKSTODAY! THIS SERVER HAS BEEN RAIDED PURELY DUE TO THE IGNORANCE OF THE SERVER OWNER. NIGGA REALLY THOUGHT HE COULD RAID A BOT DEVELOPERS SERVER LOLLLL"
        embedr = discord.Embed(
            title="GETT FUCKKEDD BY JYNKSS 🍆🍆🟩🟩🤭🤭💚🤐😜💫😜💘",
            description=f"{text}\n\n{text}",  # duplicated to mimic "sent twice"
            color=0xff5555
        )
        embedr.set_footer(text="REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD REVENGE IS A DISH BEST SERVED COLD")
        # optional image - ensure correct usage: url=...
        embedr.set_image(url="https://media.tenor.com/vkIBLYGz5O0AAAAM/im-going-to-send-nsfw-in-ur-dms.gif")
        embedr.set_thumbnail(url="https://media.tenor.com/8YQU67-dvTUAAAAM/penis.gif")  # single followup only
        for _ in range(10):
            await asyncio.sleep(0.5)
            await interaction.followup.send(embed=embedr)
        return
@tree.command(name="kaisen", description="Custom RaidMode for Muslim")
async def links_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()
    
    if not links:
        # Duplicate the message inside one embed so we only create ONE followup
        text = "JUJUTSU KAISEN IS THE BEST ❤️❤️❤️❤️"
        embedJ = discord.Embed(
            title="Yuji Itadori and Gojo",
            description=f"{text}\n\n{text}",  # duplicated to mimic "sent twice"
            color=0x00ff00
        )
        embedJ.set_footer(text="W Gojo ❤️‍🩹")
        embedJ.set_image(url="https://gifdb.com/images/high/jujutsu-kaisen-gojo-sukuna-fight-72a8dzhaor1a45vq.webp")
        embedJ.set_thumbnail(url="https://media.tenor.com/UVe_VIz4vPcAAAAM/jjk-jujutsu-kaisen.gif")  # single followup only
        for _ in range(10):
            await asyncio.sleep(0.5)
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
    await interaction.followup.send(embed=embed)

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
