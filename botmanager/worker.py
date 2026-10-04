"""Isolated bot process. JSON lines on stdin/stdout form the control channel."""
import asyncio
import importlib
import json
import os
import sys
import threading
from pathlib import Path

from .storage import JsonStore


def emit(kind, **fields):
    print(json.dumps({"protocol": "botmanager", "type": kind, **fields}), flush=True)


async def main():
    bot_id = sys.argv[1]
    data_dir = Path(os.environ["BOTMANAGER_DATA"])
    config = next(b for b in JsonStore(data_dir / "bots.json").read()["bots"] if b["id"] == bot_id)
    sys.path.insert(0, str(data_dir))
    loaded = set()
    client = None
    ready = asyncio.Event()
    done = asyncio.Event()
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def read_controls():
        for line in sys.stdin:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, line)
            except RuntimeError:
                return
        try:
            loop.call_soon_threadsafe(queue.put_nowait, "")
        except RuntimeError:
            pass

    threading.Thread(target=read_controls, daemon=True).start()

    def state(status="running"):
        emit("state", data={"status": status, "loaded": sorted(loaded), "guilds": len(client.guilds) if client else 0})

    async def extension(action, module):
        importlib.invalidate_caches()
        if action == "load" and module in loaded:
            raise ValueError("Cog is already loaded")
        if action in ("unload", "reload") and module not in loaded:
            raise ValueError("Cog is not loaded")
        if client:
            await getattr(client, f"{action}_extension")(module)
        # Demo mode simulates lifecycle without executing uploaded Python code.
        if action == "unload":
            loaded.discard(module)
        else:
            loaded.add(module)
        state()
        emit("log", message=f"{action.title()}: {module}")

    async def controls():
        while not done.is_set():
            line = await queue.get()
            if not line:
                if client:
                    await client.close()
                done.set()
                return
            request = {}
            try:
                request = json.loads(line)
                action = request["action"]
                if action == "stop":
                    emit("result", id=request["id"], ok=True)
                    if client:
                        await client.close()
                    done.set()
                    return
                if not ready.is_set():
                    raise ValueError("Bot is still connecting")
                await extension(action, request["module"])
                emit("result", id=request["id"], ok=True)
            except Exception as error:
                emit("result", id=request.get("id"), ok=False, error=str(error))
                emit("log", level="error", message=str(error))

    if config["mode"] == "discord":
        try:
            import discord
            from discord.ext import commands
        except ImportError:
            emit("log", level="error", message="Install requirements: python -m pip install -r requirements.txt")
            return 1

        class ManagedBot(commands.Bot):
            async def setup_hook(self):
                for module in config["enabled_cogs"]:
                    try:
                        await self.load_extension(module)
                        loaded.add(module)
                    except Exception as error:
                        emit("log", level="error", message=f"Cannot load {module}: {error}")

            def cog_store(self, name):
                if not name.replace("_", "").replace(".", "").isalnum():
                    raise ValueError("Invalid settings name")
                return JsonStore(data_dir / "settings" / bot_id / f"{name}.json")

        intents = discord.Intents.default()
        intents.message_content = True
        client = ManagedBot(command_prefix=config["prefix"], intents=intents)

        @client.event
        async def on_ready():
            ready.set()
            state()
            emit("log", message=f"Connected as {client.user}")

        @client.event
        async def on_disconnect():
            state("starting")

        @client.event
        async def on_command_error(ctx, error):
            if isinstance(error, commands.CommandNotFound):
                return
            emit("log", level="error", message=f"Command error: {error}")
            await ctx.send("That command could not complete. Check the bot logs.")

        control_task = asyncio.create_task(controls())
        try:
            async with client:
                await client.start(config["token"])
        except Exception as error:
            emit("log", level="error", message=f"Discord connection failed: {error}")
            return 1
        finally:
            control_task.cancel()
    else:
        loaded.update(config["enabled_cogs"])
        ready.set()
        state()
        emit("log", message="Demo started. Cog controls are simulated; no Discord connection or custom code execution.")
        await controls()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
