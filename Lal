import discord
from discord import app_commands
from discord.ext import commands
import os

TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

class Msgs(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="raid", description="RAID")
    async def msg(self, interaction: discord.Interaction):

        embed = discord.Embed(
            title="GETT FUCKKEDD BY JYNKSS 🍆🍆🟩🟩🤭🤭💚🤐😜💫😜💘",
            description="FUCK YALL!! JYNKS IS BETTER. #JOINJYNKSTODAY! THIS SERVER HAS BEEN RAIDED PURELY DUE TO THE IGNORANCE OF THE SERVER OWNER. JOIN JYNKS INSTEAD https://discord.gg/3PDwQpPrd")
        embed.set_footer(text="JYNKS")
        embed.set_thumbnail(url="https://media.tenor.com/8YQU67-dvTUAAAAM/penis.gif") # gif works here
        embed.set_image(url="https://media.tenor.com/vkIBLYGz5O0AAAAM/im-going-to-send-nsfw-in-ur-dms.gif")    # gif works here
        embed.color = 0x00ff00

        await interaction.response.send_message("sending...", ephemeral=True)
        for _ in range(20193819392):
            await  interaction.channel.send(embed=embed)

@bot.event
async def setup_hook():
    await bot.add_cog(Msgs(bot))

@bot.event
async def on_ready():
    await bot.tree.sync()
    print("ready")

bot.run(TOKEN)
