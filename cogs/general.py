import discord
from discord.ext import commands


class General(commands.Cog):
    """Basic health and greeting commands."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        await ctx.send(f"Pong! {round(self.bot.latency * 1000)} ms")

    @commands.command()
    async def hello(self, ctx):
        settings = self.bot.cog_store("cogs.general").read()
        await ctx.send(settings.get("greeting", "Hello! Your bot is up and running."), allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(General(bot))
