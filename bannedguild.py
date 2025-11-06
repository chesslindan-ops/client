import os
import re
import threading
import discord
from discord import app_commands
import aiohttp
from flask import Flask

# ---- Secrets ----
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

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

async def fetch_group_posts():
    url = f"https://groups.roblox.com/v2/groups/{GROUP_ID}/wall/posts?sortOrder=Desc&limit=100"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"}

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
    
    # remove duplicates while preserving order
    seen = set()
    unique_links = []
    for link in links:
        if link not in seen:
            seen.add(link)
            unique_links.append(link)
    
    return unique_links

@tree.command(name="links", description="Get scammer private server links! (Developed by h.aze.l)")
async def links_command(interaction: discord.Interaction):
    await interaction.response.defer(thinking=True)
    links = await fetch_group_posts()

    if not links:
        await interaction.followup.send("No roblox.com/share links found 😢")
        return

    message = "Guild/user has been blacklisted from using this service. Error code: TEST"  # send up to 10 unique links
    embed = discord.Embed(title="Links fetching failed ❌️⚠️", description=message, color=0xff0000)
    embed.set_footer(text="DM @h.aze.l for bug reports.| Made by SAB-RS")
    await interaction.followup.send(embed=embed)
    

@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash command /links is ready!")

# ---- Run Flask in background thread ----
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()  # non-daemon to keep alive

# ---- Run Discord bot in main thread ----
client.run(TOKEN)

