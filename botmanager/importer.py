"""Import native Redbot data into private, managed copies."""
import json
import os
import shutil
import uuid
from pathlib import Path

from .storage import JsonStore


def import_red(manager, source, python_exe=None):
    if not isinstance(source, str) or not source.strip():
        raise ValueError("Enter the full path to a Redbot data folder")
    source = Path(source).resolve()
    core = source / "core" / "settings.json"
    if not core.is_file() or not (source / "cogs").is_dir():
        raise ValueError("Select an instance folder containing core/settings.json and cogs/")
    if source.is_relative_to(manager.data_dir) or manager.data_dir.is_relative_to(source):
        raise ValueError("Import from a separate source folder, outside the manager data directory")
    python_exe = Path(python_exe or os.environ.get("BOTMANAGER_RED_PYTHON") or Path.home() / "redenv" / "Scripts" / "python.exe").resolve()
    if not python_exe.is_file() or python_exe.name.lower() not in ("python.exe", "python", "python3"):
        raise ValueError("Select the Python executable from the environment where Redbot is installed")
    existing = next((b for b in manager.store.read()["bots"] if b.get("import_source") == str(source)), None)
    if existing:
        raise ValueError("This instance is already imported")
    settings = JsonStore(core).read()
    try:
        global_config = settings["0"]["GLOBAL"]
        token = global_config.get("token", "")
        prefixes = global_config.get("prefix", ["!"])
        packages = global_config.get("packages", [])
        if not isinstance(token, str) or not token:
            raise ValueError("Source instance has no bot token")
        if not isinstance(prefixes, list) or not prefixes or not all(isinstance(p, str) and p for p in prefixes):
            raise ValueError("Invalid source prefixes")
        if not isinstance(packages, list) or not all(isinstance(p, str) and p.isidentifier() for p in packages):
            raise ValueError("Invalid source package list")
    except (KeyError, TypeError):
        raise ValueError("Unsupported Redbot core settings format")
    bot_id = uuid.uuid4().hex[:12]
    destination = manager.data_dir / "red_instances" / bot_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    # All source data and installed libraries are copied, never moved.
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "logs"))
    def relocate(value):
        if isinstance(value, dict):
            return {k: relocate(v) for k, v in value.items()}
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, str):
            old = str(source).replace("\\", "/").rstrip("/")
            normalized = value.replace("\\", "/")
            if normalized.lower() == old.lower() or normalized.lower().startswith(old.lower() + "/"):
                return str(destination) + normalized[len(old):].replace("/", os.sep)
        return value
    # Only Red's config files are transformed, not third-party library fixtures.
    for path in [destination / "core" / "settings.json", *destination.glob("cogs/*/settings.json")]:
        store = JsonStore(path)
        store.write(relocate(store.read()))
    config_file = manager.data_dir / "red_instances" / f"{bot_id}.json"
    JsonStore(config_file).write({bot_id: {"DATA_PATH": str(destination), "COG_PATH_APPEND": "cogs", "CORE_PATH_APPEND": "core", "STORAGE_TYPE": "JSON", "STORAGE_DETAILS": {}}})
    bot = {"id": bot_id, "name": source.name, "prefix": prefixes[0], "mode": "redbot", "token": token,
           "enabled_cogs": packages, "import_source": str(source), "red_data": str(destination),
           "red_python": str(python_exe), "red_config": str(config_file)}
    manager.store.update(lambda data: data["bots"].append(bot))
    manager.log(bot_id, "Imported native Redbot instance into managed storage; original unchanged")
    return bot_id
