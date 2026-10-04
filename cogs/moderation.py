import discord
from discord.ext import commands


class Moderation(commands.Cog):
    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 5):
        """Delete up to 100 recent messages."""
        if not 1 <= amount <= 100:
            await ctx.send("Choose a number between 1 and 100.")
            return
        deleted = await ctx.channel.purge(limit=amount + 1)
        await ctx.send(f"Cleared {max(0, len(deleted) - 1)} messages.", delete_after=5, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Moderation())
