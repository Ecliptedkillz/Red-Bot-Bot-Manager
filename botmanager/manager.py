import ast
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from pathlib import Path

from .storage import JsonStore
from .config import normalize_co_owners

ROOT = Path(__file__).resolve().parent.parent
NAME = re.compile(r"^[a-z][a-z0-9_]{0,47}$")


class Manager:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or ROOT / "data").resolve()
        self.store = JsonStore(self.data_dir / "bots.json", {"bots": []})
        self.lock = threading.RLock()
        self.processes = {}
        self.states = {}
        self.logs = {}
        self.pending = {}
        self.custom = self.data_dir / "custom_cogs"
        self.custom.mkdir(parents=True, exist_ok=True)
        (self.custom / "__init__.py").touch(exist_ok=True)

    def bot(self, bot_id):
        for bot in self.store.read()["bots"]:
            if bot["id"] == bot_id:
                return bot
        raise ValueError("Bot not found")

    def log(self, bot_id, message, level="info"):
        with self.lock:
            token = next((b.get("token") for b in self.store.read()["bots"] if b["id"] == bot_id), None)
            if token:
                message = str(message).replace(token, "[redacted]")
            self.logs.setdefault(bot_id, deque(maxlen=300)).append({"time": time.strftime("%H:%M:%S"), "level": level, "message": str(message)[:4000]})

    def snapshot(self):
        with self.lock:
            bots = []
            for bot in self.store.read()["bots"]:
                public = {k: v for k, v in bot.items() if k != "token"}
                public["has_token"] = bool(bot.get("token"))
                if bot.get("mode") == "redbot":
                    public["cog_catalog"] = self.cogs(bot["id"])
                state = self.states.get(bot["id"], {"status": "stopped", "loaded": [], "guilds": 0})
                public.update(state)
                public["uptime"] = int(time.time() - state["started"]) if state.get("started") and state["status"] in ("running", "starting") else 0
                bots.append(public)
            return {"bots": bots, "cogs": self.cogs()}

    def cogs(self, bot_id=None):
        if bot_id:
            bot = self.bot(bot_id)
            if bot.get("mode") == "redbot":
                base = Path(bot["red_data"])
                packages = set(bot["enabled_cogs"])
                for directory in (base / "cogs" / "CogManager" / "cogs", Path(bot["red_python"]).parent.parent / "Lib" / "site-packages" / "redbot" / "cogs"):
                    if directory.exists():
                        packages.update(p.name for p in directory.iterdir() if p.is_dir() and (p / "__init__.py").is_file() and p.name.isidentifier() and not p.name.startswith("_"))
                result = [{"name": name, "module": name, "kind": "Redbot", "has_settings": False} for name in sorted(packages)]
                for path in sorted(base.glob("cogs/*/settings.json")):
                    if path.parent.name.isidentifier():
                        result.append({"name": f"{path.parent.name} settings", "module": f"config:{path.parent.name}", "kind": "Redbot JSON", "settings_only": True})
                return result
        result = []
        for directory, kind in ((ROOT / "cogs", "built-in"), (self.custom, "custom")):
            for path in sorted(directory.glob("*.py")):
                if not path.stem.startswith("_"):
                    result.append({"name": path.stem, "module": f'{"cogs" if kind == "built-in" else "custom_cogs"}.{path.stem}', "kind": kind})
        return result

    def save_bot(self, payload, bot_id=None):
        with self.lock:
            old = self.bot(bot_id) if bot_id else {}
            if bot_id and self.processes.get(bot_id) and self.processes[bot_id].poll() is None:
                raise ValueError("Stop the bot before editing its settings")
            name = payload.get("name", old.get("name", ""))
            prefix = payload.get("prefix", old.get("prefix", "!"))
            mode = payload.get("mode", old.get("mode", "demo"))
            token = payload.get("token") or old.get("token", "")
            if not isinstance(name, str) or not name.strip() or len(name) > 80:
                raise ValueError("Name must contain 1–80 characters")
            if not isinstance(prefix, str) or not prefix or len(prefix) > 16:
                raise ValueError("Prefix must contain 1–16 characters")
            if mode not in ("demo", "discord", "redbot") or not isinstance(token, str):
                raise ValueError("Invalid mode or token")
            if mode == "redbot" and old.get("mode") != "redbot":
                raise ValueError("Use Import bot for native Redbot instances")
            if old.get("mode") == "redbot" and mode != "redbot":
                raise ValueError("An imported Redbot instance must keep its native runtime")
            if mode == "discord" and not token:
                raise ValueError("A Discord bot token is required")
            bot = {**old, "id": bot_id or uuid.uuid4().hex[:12], "name": name.strip(), "prefix": prefix, "mode": mode, "token": token, "enabled_cogs": old.get("enabled_cogs", ["cogs.general"])}
            if mode == "redbot":
                bot["red_co_owner_ids"] = normalize_co_owners(payload.get("red_co_owner_ids", old.get("red_co_owner_ids", [])))
                def update_core(data):
                    data["0"]["GLOBAL"]["token"] = token
                    if prefix != old["prefix"]:
                        data["0"]["GLOBAL"]["prefix"] = [prefix]
                JsonStore(Path(old["red_data"]) / "core" / "settings.json").update(update_core)
            def update(data):
                data["bots"] = [b for b in data["bots"] if b["id"] != bot["id"]] + [bot]
            self.store.update(update)
            self.log(bot["id"], "Bot settings saved")
            return bot["id"]

    def start(self, bot_id):
        with self.lock:
            bot = self.bot(bot_id)
            if bot_id in self.processes and self.processes[bot_id].poll() is None:
                raise ValueError("Bot is already running")
            self.states[bot_id] = {"status": "starting", "loaded": [], "guilds": 0, "started": time.time()}
            env = dict(os.environ, BOTMANAGER_DATA=str(self.data_dir), PYTHONUNBUFFERED="1")
            if bot["mode"] == "redbot":
                # Red otherwise lets a global RED_TOKEN override the instance token.
                env.pop("RED_TOKEN", None)
            executable = bot.get("red_python", sys.executable) if bot["mode"] == "redbot" else sys.executable
            worker = "botmanager.red_worker" if bot["mode"] == "redbot" else "botmanager.worker"
            process = subprocess.Popen([executable, "-m", worker, bot_id], cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.processes[bot_id] = process
            threading.Thread(target=self._read, args=(bot_id, process), daemon=True).start()
            self.log(bot_id, "Starting bot process")

    def _read(self, bot_id, process):
        for line in process.stdout:
            try:
                event = json.loads(line)
                if not isinstance(event, dict) or event.get("protocol") != "botmanager":
                    raise ValueError()
            except (ValueError, TypeError):
                self.log(bot_id, line.rstrip())
                continue
            with self.lock:
                if event.get("type") == "state":
                    if self.processes.get(bot_id) is process:
                        self.states[bot_id].update(event["data"])
                elif event.get("type") == "result":
                    pending = self.pending.get(event.get("id"))
                    if pending:
                        pending["result"] = event
                        pending["event"].set()
                elif event.get("type") == "log":
                    self.log(bot_id, event.get("message", ""), event.get("level", "info"))
        code = process.wait()
        process.stdin.close()
        process.stdout.close()
        with self.lock:
            if self.processes.get(bot_id) is process:
                state = self.states[bot_id]
                state.update(status="stopped" if code == 0 or state.get("status") == "stopping" else "error", loaded=[], guilds=0)
            self.log(bot_id, f"Process exited (code {code})", "info" if code == 0 else "error")

    def command(self, bot_id, action, module=None):
        request_id = uuid.uuid4().hex
        pending = {"event": threading.Event()}
        with self.lock:
            self.bot(bot_id)
            process = self.processes.get(bot_id)
            if not process or process.poll() is not None:
                raise ValueError("Bot is not running")
            self.pending[request_id] = pending
            try:
                process.stdin.write(json.dumps({"id": request_id, "action": action, "module": module}) + "\n")
                process.stdin.flush()
            except (OSError, ValueError):
                self.pending.pop(request_id, None)
                raise ValueError("Bot process is unavailable")
        try:
            if not pending["event"].wait(15):
                raise ValueError("Bot did not respond in time; check its logs")
            if not pending["result"].get("ok"):
                raise ValueError(pending["result"].get("error", "Command failed"))
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def stop(self, bot_id):
        with self.lock:
            bot = self.bot(bot_id)
            process = self.processes.get(bot_id)
            if not process or process.poll() is not None:
                return
            self.states[bot_id]["status"] = "stopping"
        try:
            self.command(bot_id, "stop")
        except ValueError:
            pass
        try:
            process.wait(timeout=20 if bot["mode"] == "redbot" else 5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        with self.lock:
            self.states[bot_id].update(status="stopped", loaded=[], guilds=0)

    def cog_action(self, bot_id, module, action):
        if module not in {c["module"] for c in self.cogs(bot_id) if not c.get("settings_only")} or action not in ("load", "unload", "reload"):
            raise ValueError("Invalid cog or action")
        self.command(bot_id, action, module)
        def update(data):
            bot = next(b for b in data["bots"] if b["id"] == bot_id)
            enabled = set(bot["enabled_cogs"])
            if action == "unload":
                enabled.discard(module)
            else:
                enabled.add(module)
            bot["enabled_cogs"] = sorted(enabled)
        self.store.update(update)

    def upload(self, name, source):
        if not isinstance(name, str) or not NAME.fullmatch(name) or name in ("__init__",):
            raise ValueError("Use a lowercase Python name, such as welcome")
        if not isinstance(source, str) or len(source.encode("utf-8")) > 200_000:
            raise ValueError("Cog source must be under 200 KB")
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            raise ValueError(f"Python syntax error on line {error.lineno}: {error.msg}")
        if not any(isinstance(node, ast.AsyncFunctionDef) and node.name == "setup" for node in tree.body):
            raise ValueError("Cog must define async def setup(bot)")
        path = self.custom / f"{name}.py"
        with self.lock:
            if path.exists():
                raise ValueError("Cog already exists; edit its file and use Reload")
            path.write_text(source, encoding="utf-8")

    def cog_settings(self, bot_id, module, settings=None):
        bot = self.bot(bot_id)
        if module not in {c["module"] for c in self.cogs(bot_id)}:
            raise ValueError("Unknown cog")
        if bot.get("mode") == "redbot":
            if not module.startswith("config:"):
                raise ValueError("Use a Redbot JSON settings entry to edit saved cog data")
            if settings is not None and self.processes.get(bot_id) and self.processes[bot_id].poll() is None:
                raise ValueError("Stop Redbot before editing native settings; Red caches JSON data")
            store = JsonStore(Path(bot["red_data"]) / "cogs" / module.split(":", 1)[1] / "settings.json")
        else:
            store = JsonStore(self.data_dir / "settings" / bot_id / f"{module}.json")
        if settings is not None:
            if not isinstance(settings, dict):
                raise ValueError("Cog settings must be a JSON object")
            store.write(settings)
        return store.read()

    def import_bot(self, source, python_exe=None):
        from .importer import import_red
        with self.lock:
            return import_red(self, source, python_exe)

    def delete(self, bot_id):
        self.stop(bot_id)
        self.store.update(lambda data: data.update(bots=[b for b in data["bots"] if b["id"] != bot_id]))
        with self.lock:
            self.processes.pop(bot_id, None)
            self.states.pop(bot_id, None)
            self.logs.pop(bot_id, None)

    def shutdown(self):
        for bot_id in list(self.processes):
            self.stop(bot_id)
