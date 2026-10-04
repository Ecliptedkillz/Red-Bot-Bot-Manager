"""Run with an existing Redbot environment; uses a fake cog and no network."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock
from unittest.mock import patch, PropertyMock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from botmanager.manager import Manager
from botmanager.storage import JsonStore
from redbot import _early_init

_early_init()
import redbot.__main__ as redmain
from redbot.core import data_manager, _drivers
from redbot.core._cli import parse_cli_flags
from redbot.core.core_commands import Core
from botmanager import red_worker


def check():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source = root / "source"
        package = source / "cogs" / "CogManager" / "cogs" / "portaltest"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text('from redbot.core import commands\nclass PortalTest(commands.Cog):\n    pass\nasync def setup(bot):\n    await bot.add_cog(PortalTest())\n', encoding="utf-8")
        JsonStore(source / "core/settings.json").write({"0": {"GLOBAL": {"token": "offline-placeholder", "prefix": ["!"], "packages": []}}})
        manager = Manager(root / "manager")
        bot_id = manager.import_bot(str(source), sys.executable)
        manager.save_bot({"red_co_owner_ids": ["713265432383193159"]}, bot_id)
        os.environ["BOTMANAGER_DATA"] = str(manager.data_dir)
        sys.argv = ["check_red_runtime", bot_id]
        events = []
        red_worker.emit = lambda kind, **fields: events.append({"type": kind, **fields})

        async def verify(bot):
            await bot._async_setup_hook()
            bot.register_rpc_handler = lambda method: None
            bot.unregister_rpc_handler = lambda method: None
            await bot.add_cog(Core(bot))
            bot._ready.set()
            for action in ("load", "reload", "unload"):
                await bot.portal_queue.put(json.dumps({"id": action, "action": action, "module": "portaltest"}) + "\n")
                for _ in range(100):
                    if any(e.get("id") == action for e in events):
                        break
                    await asyncio.sleep(.03)
                result = next(e for e in events if e.get("id") == action)
                assert result["ok"], result
                assert ("portaltest" in bot.extensions) == (action != "unload")
            bot.shutdown = AsyncMock()
            await bot.portal_queue.put(json.dumps({"id": "stop", "action": "stop"}) + "\n")
            await asyncio.sleep(.1)
            bot.shutdown.assert_awaited_once()
            await bot.close()

        def offline_main():
            assert data_manager.config_file == Path(manager.bot(bot_id)["red_config"])
            flags = parse_cli_flags(sys.argv[1:])
            assert flags.co_owner == [713265432383193159], flags.co_owner
            data_manager.load_basic_configuration(flags.instance_name)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            driver = _drivers.get_driver_class()
            try:
                loop.run_until_complete(driver.initialize(**data_manager.storage_details()))
                bot = redmain.Red(cli_flags=flags)
                with patch.object(type(bot), "application", new_callable=PropertyMock) as application:
                    application.return_value = SimpleNamespace(team=SimpleNamespace(members=[]))
                    bot._setup_owners()
                    assert 713265432383193159 in bot.owner_ids
                loop.run_until_complete(verify(bot))
            finally:
                for task in asyncio.all_tasks(loop):
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*asyncio.all_tasks(loop), return_exceptions=True))
                loop.run_until_complete(driver.teardown())
                loop.close()

        redmain.main = offline_main
        reader, writer = os.pipe()
        original_stdin = sys.stdin
        sys.stdin = os.fdopen(reader, "r")
        try:
            red_worker.main()
        finally:
            os.close(writer)
            sys.stdin.close()
            sys.stdin = original_stdin
        print("Native Redbot bridge: load, reload, unload, stop, and private registry passed offline.")


if __name__ == "__main__":
    check()
