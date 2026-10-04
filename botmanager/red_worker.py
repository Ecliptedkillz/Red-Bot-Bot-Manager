"""Run Red's own entry point with a private registry and portal control bridge."""
import asyncio
import json
import os
import sys
import threading
import time
import traceback
import importlib
from pathlib import Path

from .storage import JsonStore
from .worker import emit
from .config import red_launch_args


def main():
    bot_id = sys.argv[1]
    config = next(b for b in JsonStore(Path(os.environ["BOTMANAGER_DATA"]) / "bots.json").read()["bots"] if b["id"] == bot_id)
    # Initialize bundled numerical DLLs before concurrent cog/background tasks.
    # NumPy's native import can block the event loop, defeating async load timeouts.
    library_path = Path(config["red_data"]) / "cogs" / "Downloader" / "lib"
    sys.path.append(str(library_path))
    for variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ.setdefault(variable, "1")
    if (library_path / "numpy").is_dir():
        emit("log", message="Initializing numerical libraries before cog startup")
        importlib.import_module("numpy")
        emit("log", message="Numerical libraries initialized")
    from redbot import _early_init
    _early_init()
    import redbot.__main__ as redmain
    from redbot.core import data_manager
    data_manager.config_file = Path(config["red_config"])
    data_manager.config_dir = data_manager.config_file.parent
    base = redmain.Red

    class PortalRed(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            loop = asyncio.get_event_loop()
            self.portal_queue = asyncio.Queue()
            self.portal_phase = "Connecting to Discord"
            self.portal_phase_started = time.monotonic()
            self.portal_phase_reported = False
            self.portal_phase_pending = True
            original_find_cog = self._cog_mgr.find_cog

            async def find_cog(name):
                self.set_phase(f"Finding cog: {name}")
                return await asyncio.wait_for(original_find_cog(name), timeout=30)

            self._cog_mgr.find_cog = find_cog
            self.add_listener(self.portal_ready, "on_ready")
            self.add_listener(self.portal_disconnect, "on_disconnect")
            loop.create_task(self.portal_controls())
            loop.create_task(self.portal_status())
            def reader():
                for line in sys.stdin:
                    try:
                        loop.call_soon_threadsafe(self.portal_queue.put_nowait, line)
                    except RuntimeError:
                        return
                try:
                    loop.call_soon_threadsafe(self.portal_queue.put_nowait, "")
                except RuntimeError:
                    pass
            threading.Thread(target=reader, daemon=True).start()
            # This thread still reports a Python stack if a cog blocks the event loop.
            main_thread = threading.get_ident()
            def watchdog():
                while not loop.is_closed():
                    time.sleep(5)
                    if self.portal_phase_pending and not self.portal_phase_reported and time.monotonic() - self.portal_phase_started > 45:
                        self.portal_phase_reported = True
                        emit("log", level="error", message=f"Startup stalled: {self.portal_phase}")
                        frame = sys._current_frames().get(main_thread)
                        if frame:
                            emit("log", level="error", message="".join(traceback.format_stack(frame, limit=10)))
            threading.Thread(target=watchdog, daemon=True).start()

        def set_phase(self, phase):
            self.portal_phase = phase
            self.portal_phase_started = time.monotonic()
            self.portal_phase_reported = False
            self.portal_phase_pending = phase.startswith(("Connecting", "Reconnecting", "Finding cog:", "Loading cog:"))
            self.emit_state("running" if self.is_ready() else "starting")
            emit("log", message=phase)

        async def load_extension(self, spec):
            name = spec.name.split(".")[-1]
            self.set_phase(f"Loading cog: {name}")
            try:
                await super().load_extension(spec)
            except BaseException:
                self.set_phase(f"Cog failed: {name}")
                emit("log", level="error", message=f"Cog did not load: {name}")
                raise
            self.set_phase(f"Loaded cog: {name}")

        def emit_state(self, status="running"):
            emit("state", data={"status": status, "loaded": sorted(self.extensions), "guilds": len(self.guilds), "phase": self.portal_phase})

        async def portal_ready(self):
            self.portal_phase = "Connected"
            self.portal_phase_pending = False
            self.portal_phase_started = float("inf")
            self.emit_state()
            emit("log", message=f"Redbot connected as {self.user}")

        async def portal_disconnect(self):
            self.set_phase("Reconnecting to Discord")

        async def portal_status(self):
            while not self.is_closed():
                await asyncio.sleep(3)
                if self.is_ready():
                    self.emit_state()
                else:
                    self.emit_state("starting")

        async def portal_controls(self):
            while True:
                line = await self.portal_queue.get()
                if not line:
                    await self.shutdown()
                    return
                request = {}
                try:
                    request = json.loads(line)
                    action = request["action"]
                    if action == "stop":
                        emit("result", id=request["id"], ok=True)
                        await self.shutdown()
                        return
                    if not self.is_ready():
                        raise ValueError("Redbot is still connecting")
                    module = request["module"]
                    if action not in ("load", "unload", "reload") or not module.isidentifier():
                        raise ValueError("Invalid Redbot cog action")
                    if action in ("unload", "reload") and module not in self.extensions:
                        raise ValueError("Cog is not loaded")
                    if action == "load" and module in self.extensions:
                        raise ValueError("Cog is already loaded")
                    core = self.get_cog("Core")
                    result = await getattr(core, f"_{action}")([module])
                    key = "unloaded_packages" if action == "unload" else "loaded_packages"
                    if module not in result.get(key, []):
                        raise ValueError(f"Cog {action} failed: {result}")
                    self.emit_state()
                    emit("result", id=request["id"], ok=True)
                    emit("log", message=f"{action.title()}: {module}")
                except Exception as error:
                    emit("result", id=request.get("id"), ok=False, error=str(error))

    redmain.Red = PortalRed
    sys.argv = red_launch_args(config)
    redmain.main()


if __name__ == "__main__":
    main()
