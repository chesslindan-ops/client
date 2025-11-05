import threading
import os
import discord
from discord import app_commands
import aiohttp
import asyncio
from flask import Flask

# secrets
TOKEN = os.getenv("DISCORD_TOKEN")
GROUP_ID = os.getenv("GROUP_ID")
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

# Flask
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot alive!", 200

def run_flask():
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# start flask in background
flask_thread = threading.Thread(target=run_flask)
flask_thread.start()  # not daemon, so it keeps alive

# Discord bot
intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ... your fetch_group_posts and commands here ...

@client.event
async def on_ready():
    await tree.sync()
    print(f"✅ Logged in as {client.user}")
    print("Slash command /links is now ready!")

# run bot in main thread (blocking)
client.run(TOKEN)
