import discord
from discord import app_commands
import asyncio, os, re, aiohttp

TOKEN = os.getenv("DISCORD_TOKEN")   # store this in Replit secrets
GROUP_ID = os.getenv("GROUP_ID")     # store your group ID
ROBLOX_COOKIE = os.getenv("ROBLOX_COOKIE")

class LinkBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.default())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()
        print("✅ Slash commands synced.")

client = LinkBot()

async def fetch_group_wall(session, group_id):
    url = f"https://groups.roblox.com/v1/groups/{group_id}/wall/posts?limit=10"
    headers = {"Cookie": f".ROBLOSECURITY={ROBLOX_COOKIE}"}
    async with session.get(url, headers=headers) as resp:
        if resp.status != 200:
            print(f"Error: {resp.status}")
            return []
        data = await resp.json()
        return data.get("data", [])

@client.tree.command(name="getlinks", description="Fetch recent Roblox links from the group wall")
async def getlinks(interaction: discord.Interaction):
    await interaction.response.defer()
    async with aiohttp.ClientSession() as session:
        posts = await fetch_group_wall(session, GROUP_ID)
        all_links = []
        for post in posts:
            body = post.get("body", "")
            links = re.findall(r"https?://[^\s]+", body)
            all_links.extend(links)

    if not all_links:
        await interaction.followup.send("No links found in recent posts.")
    else:
        msg = "**🔗 New Roblox Share Links:**\n" + "\n".join(f"• {l}" for l in all_links)
        await interaction.followup.send(msg[:2000])  # Discord message limit

client.run(TOKEN)
