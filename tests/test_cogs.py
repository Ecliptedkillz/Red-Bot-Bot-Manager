import unittest
from unittest.mock import AsyncMock

try:
    import discord
    from discord.ext import commands
except ImportError:
    discord = None


@unittest.skipIf(discord is None, "Install requirements to test Discord extensions")
class CogTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_extension_load_reload_unload(self):
        async with commands.Bot(command_prefix="!", intents=discord.Intents.default()) as bot:
            await bot.load_extension("cogs.general")
            self.assertIsNotNone(bot.get_command("ping"))
            self.assertIsNotNone(bot.get_command("hello"))
            await bot.reload_extension("cogs.general")
            self.assertEqual(len([c for c in bot.commands if c.name == "ping"]), 1)
            await bot.load_extension("cogs.moderation")
            self.assertEqual(len(bot.get_command("clear").checks), 3)
            await bot.unload_extension("cogs.general")
            self.assertIsNone(bot.get_command("ping"))
            self.assertNotIn("cogs.general", bot.extensions)

    async def test_greeting_reads_latest_settings(self):
        from cogs.general import General
        class Store:
            value = {"greeting": "First greeting"}
            def read(self):
                return self.value
        store = Store()
        class Bot:
            def cog_store(self, name):
                assert name == "cogs.general"
                return store
        cog = General(Bot())
        ctx = AsyncMock()
        await cog.hello.callback(cog, ctx)
        self.assertEqual(ctx.send.call_args.args[0], "First greeting")
        store.value = {"greeting": "Updated greeting"}
        await cog.hello.callback(cog, ctx)
        self.assertEqual(ctx.send.call_args.args[0], "Updated greeting")


if __name__ == "__main__":
    unittest.main()
