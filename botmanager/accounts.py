"""JSON accounts, password hashes, and server-side authorization."""
import hashlib
import hmac
import re
import secrets
import uuid

from .storage import JsonStore

SITE_PERMISSIONS = {"bots.create": "Create bots", "bots.import": "Import native bots (trusted code)",
                    "cogs.view": "View shared cog library", "cogs.upload": "Upload executable cogs (trusted code)"}
BOT_PERMISSIONS = {"view": "View bot", "control": "Start / stop / restart", "logs": "Read console",
                   "cogs": "Load / unload / reload cogs", "settings.read": "Read cog JSON",
                   "settings.write": "Edit cog JSON", "configure": "Edit bot configuration / token / Redbot owners",
                   "delete": "Delete bot"}


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=32768, r=8, p=3, maxmem=64 * 1024**2).hex()
    return f"scrypt$32768$8$3${salt}${digest}"


def check_password(password, encoded):
    try:
        fields = encoded.split("$")
        if len(fields) == 3:
            algorithm, salt, expected = fields
            n, r, p = 16384, 8, 1
        else:
            algorithm, n, r, p, salt, expected = fields
            n, r, p = int(n), int(r), int(p)
            if (n, r, p) != (32768, 8, 3):
                return False
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=n, r=r, p=p, maxmem=64 * 1024**2).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def allowed(account, permission, bot_id=None):
    if not account or account.get("disabled"):
        return False
    if account["role"] == "admin":
        return True
    if bot_id is None:
        return permission in account["site_permissions"]
    permissions = account["bot_permissions"].get(bot_id, account["bot_defaults"])
    return "view" in permissions and permission in permissions


class Accounts:
    def __init__(self, path, bootstrap_password, username="admin"):
        self.store = JsonStore(path, {"accounts": []})
        self.bootstrap_username = username
        self.created_admin = False
        # The environment password only seeds the first admin; it is never a bypass.
        if not self.store.read()["accounts"]:
            self.save({"username": username, "password": bootstrap_password, "role": "admin"}, bootstrap=True)
            self.created_admin = True
        self.dummy_hash = hash_password(secrets.token_urlsafe(32))

    @staticmethod
    def public(account):
        return {k: v for k, v in account.items() if k not in ("password_hash", "version")}

    def get(self, account_id):
        return next((a for a in self.store.read()["accounts"] if a["id"] == account_id), None)

    def authenticate(self, username, password):
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1024:
            return None
        account = next((a for a in self.store.read()["accounts"] if a["username"].casefold() == username.strip().casefold()), None)
        valid = check_password(password, account["password_hash"] if account else self.dummy_hash)
        return account if valid and account and not account["disabled"] else None

    def save(self, payload, account_id=None, bootstrap=False):
        with self.store.lock:
            data = self.store.read()
            old = next((a for a in data["accounts"] if a["id"] == account_id), None) if account_id else None
            if account_id and not old:
                raise ValueError("Account not found")
            username = payload.get("username", (old or {}).get("username", ""))
            if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
                raise ValueError("Username must be 3–40 letters, numbers, dots, underscores, or hyphens")
            if any(a["id"] != account_id and a["username"].casefold() == username.casefold() for a in data["accounts"]):
                raise ValueError("Username is already in use")
            role = payload.get("role", (old or {}).get("role", "member"))
            disabled = payload.get("disabled", (old or {}).get("disabled", False))
            if role not in ("admin", "member") or not isinstance(disabled, bool):
                raise ValueError("Invalid role or disabled flag")
            password = payload.get("password", "")
            if not isinstance(password, str) or (password and not bootstrap and not 8 <= len(password) <= 1024):
                raise ValueError("Passwords must contain 8–1024 characters")
            if not old and not password:
                raise ValueError("A password is required for new accounts")
            def permissions(value, valid):
                if not isinstance(value, list) or not all(isinstance(p, str) and p in valid for p in value):
                    raise ValueError("Unknown permission")
                return sorted(set(value))
            site = permissions(payload.get("site_permissions", (old or {}).get("site_permissions", [])), SITE_PERMISSIONS)
            defaults = permissions(payload.get("bot_defaults", (old or {}).get("bot_defaults", [])), BOT_PERMISSIONS)
            overrides = payload.get("bot_permissions", (old or {}).get("bot_permissions", {}))
            if not isinstance(overrides, dict) or not all(re.fullmatch(r"[a-f0-9]{12}", k) for k in overrides):
                raise ValueError("Invalid bot permissions")
            overrides = {k: permissions(v, BOT_PERMISSIONS) for k, v in overrides.items()}
            account = {"id": account_id or uuid.uuid4().hex, "username": username, "role": role, "disabled": disabled,
                       "site_permissions": site, "bot_defaults": defaults, "bot_permissions": overrides,
                       "password_hash": hash_password(password) if password else old["password_hash"],
                       "version": (old or {}).get("version", 0) + 1}
            updated = [a for a in data["accounts"] if a["id"] != account["id"]] + [account]
            if not any(a["role"] == "admin" and not a["disabled"] for a in updated):
                raise ValueError("At least one enabled administrator must remain")
            self.store.write({"accounts": updated})
            return self.public(account)

    def delete(self, account_id):
        with self.store.lock:
            data = self.store.read()
            if not any(a["id"] == account_id for a in data["accounts"]):
                raise ValueError("Account not found")
            remaining = [a for a in data["accounts"] if a["id"] != account_id]
            if not any(a["role"] == "admin" and not a["disabled"] for a in remaining):
                raise ValueError("At least one enabled administrator must remain")
            self.store.write({"accounts": remaining})

    def grant_created_bot(self, account_id, bot_id):
        def update(data):
            account = next(a for a in data["accounts"] if a["id"] == account_id)
            account["bot_permissions"][bot_id] = list(BOT_PERMISSIONS)
        self.store.update(update)
