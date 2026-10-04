"""Small, literal .env loader: values are never evaluated as commands."""
import os
import re
from pathlib import Path
from urllib.parse import urlsplit


def normalize_co_owners(value):
    if isinstance(value, str):
        value = value.replace(",", " ").split()
    if not isinstance(value, list) or len(value) > 20:
        raise ValueError("Co-owner IDs must be a list of up to 20 Discord user IDs")
    result = []
    for item in value:
        text = str(item)
        if not re.fullmatch(r"[0-9]{1,20}", text) or not 0 < int(text) < 2**64:
            raise ValueError("Each co-owner ID must be a positive Discord user ID")
        text = str(int(text))
        if text not in result:
            result.append(text)
    return result


def red_launch_args(config):
    args = ["redbot", config["id"], "--no-prompt"]
    for user_id in normalize_co_owners(config.get("red_co_owner_ids", [])):
        args.extend(["--co-owner", user_id])
    return args


def load_env(path):
    path = Path(path)
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError(f"Invalid .env entry on line {number}")
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def public_origin(value):
    if not value:
        return None
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
        raise ValueError("BOTMANAGER_PUBLIC_URL must be an HTTPS origin, e.g. https://bots.eclipted.com")
    # Validate the port and normalize a conventional HTTPS port.
    port = parsed.port
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    return f"https://{host}" + (f":{port}" if port and port != 443 else "")
