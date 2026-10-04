import argparse
import getpass
import json
import mimetypes
import os
import secrets
import re
import threading
import time
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl

from .manager import Manager, ROOT
from .config import load_env, public_origin
from .accounts import Accounts, allowed, SITE_PERMISSIONS, BOT_PERMISSIONS


class Portal(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, manager, password, public_url=None, admin_username="admin"):
        super().__init__(address, Handler)
        self.manager = manager
        self.accounts = Accounts(manager.data_dir / "accounts.json", password, admin_username)
        self.public_origin = public_origin(public_url)
        self.sessions = {}
        self.failures = []
        self.auth_lock = threading.Lock()
        self.operations = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def handle(self):
        try:
            super().handle()
        except (ConnectionResetError, BrokenPipeError):
            pass

    def log_message(self, *args):
        pass

    def send(self, status, body, content_type="application/json", cookie=None):
        if content_type == "application/json":
            body = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def valid_host(self):
        return self.request_origin() is not None

    def request_origin(self):
        host = self.headers.get("Host", "")
        if self.server.public_origin and host == urlsplit(self.server.public_origin).netloc:
            return self.server.public_origin
        port = self.server.server_address[1]
        if host in (f"localhost:{port}", f"127.0.0.1:{port}"):
            return f"http://{host}"
        return None

    def session_cookie(self, session, max_age):
        secure = "; Secure" if (self.request_origin() or "").startswith("https://") else ""
        return f"session={session}; HttpOnly; SameSite=Strict; Path=/; Max-Age={max_age}{secure}"

    def current_user(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
            session = cookie.get("session")
            if not session:
                return None
            with self.server.auth_lock:
                record = self.server.sessions.get(session.value)
                if not record or record["expires"] <= time.time():
                    return None
                account = self.server.accounts.get(record["account_id"])
                if not account or account["disabled"] or account["version"] != record["version"]:
                    return None
                return account
        except Exception:
            return None

    def authenticated(self):
        return self.current_user() is not None

    def require(self, user, permission, bot_id=None):
        if not allowed(user, permission, bot_id):
            raise PermissionError("You do not have permission for this action")

    def filtered_state(self, user):
        state = self.server.manager.snapshot()
        state["bots"] = [bot for bot in state["bots"] if allowed(user, "view", bot["id"])]
        for bot in state["bots"]:
            bot["permissions"] = [key for key in BOT_PERMISSIONS if allowed(user, key, bot["id"])]
            if not allowed(user, "configure", bot["id"]):
                for key in ("red_python", "red_config", "red_data", "import_source", "red_co_owner_ids"):
                    bot.pop(key, None)
            if "cog_catalog" in bot:
                bot["cog_catalog"] = [cog for cog in bot["cog_catalog"] if allowed(user, "settings.read" if cog.get("settings_only") else "cogs", bot["id"])]
        if not allowed(user, "cogs.view") and not any(allowed(user, "cogs", bot["id"]) or allowed(user, "settings.read", bot["id"]) for bot in state["bots"]):
            state["cogs"] = []
        state["user"] = self.server.accounts.public(user)
        return state

    def do_GET(self):
        if not self.valid_host():
            return self.send(403, {"error": "Invalid host"})
        path = urlsplit(self.path).path
        # Strip accidental legacy password queries before rendering any page/assets.
        if any(key.casefold() == "password" for key, value in parse_qsl(urlsplit(self.path).query)):
            self.send_response(303)
            self.send_header("Location", path)
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            return
        if path == "/api/session":
            user = self.current_user()
            return self.send(200, {"authenticated": bool(user), "user": self.server.accounts.public(user) if user else None})
        if path.startswith("/api/"):
            user = self.current_user()
            if not user:
                return self.send(401, {"error": "Sign in to continue"})
            try:
                pieces = path.strip("/").split("/")
                if path == "/api/state":
                    return self.send(200, self.filtered_state(user))
                if path == "/api/accounts":
                    if user["role"] != "admin":
                        raise PermissionError("Administrator access required")
                    return self.send(200, {"accounts": [self.server.accounts.public(a) for a in self.server.accounts.store.read()["accounts"]],
                                           "site_permissions": SITE_PERMISSIONS, "bot_permissions": BOT_PERMISSIONS})
                if len(pieces) == 4 and pieces[1] == "bots" and pieces[3] == "logs":
                    self.require(user, "logs", pieces[2])
                    self.server.manager.bot(pieces[2])
                    with self.server.manager.lock:
                        logs = list(self.server.manager.logs.get(pieces[2], []))
                    return self.send(200, {"logs": logs})
                if len(pieces) == 5 and pieces[1] == "bots" and pieces[3] == "settings":
                    self.require(user, "settings.read", pieces[2])
                    return self.send(200, {"settings": self.server.manager.cog_settings(pieces[2], pieces[4])})
                return self.send(404, {"error": "Route not found"})
            except ValueError as error:
                return self.send(400, {"error": str(error)})
            except PermissionError as error:
                return self.send(403, {"error": str(error)})
        assets = {"/": "index.html", "/app.js": "app.js", "/admin.js": "admin.js", "/routes.js": "routes.js", "/style.css": "style.css"}
        if re.fullmatch(r"/(?:admin|cogs(?:/new)?|logs|bots/(?:new|import|[a-f0-9]{12}(?:/(?:console|settings|cogs(?:/[^/]+/settings)?))?))/?", path):
            assets[path] = "index.html"
        if path not in assets:
            return self.send(404, {"error": "Not found"})
        file = ROOT / "web" / assets[path]
        mime = "application/javascript" if file.suffix == ".js" else (mimetypes.guess_type(file)[0] or "text/plain")
        self.send(200, file.read_bytes(), mime + "; charset=utf-8")

    def do_POST(self):
        if not self.valid_host() or self.headers.get("Origin") != self.request_origin():
            return self.send(403, {"error": "Requests must come from this portal"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 300_000:
                return self.send(413, {"error": "Request too large or empty"})
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                return self.send(415, {"error": "JSON required"})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            path = urlsplit(self.path).path
            if path == "/api/login":
                with self.server.auth_lock:
                    now = time.time()
                    self.server.failures = [t for t in self.server.failures if now - t < 60]
                    if len(self.server.failures) >= 10:
                        return self.send(429, {"error": "Too many attempts. Try again in a minute."})
                    account = self.server.accounts.authenticate(payload.get("username", self.server.accounts.bootstrap_username), payload.get("password", ""))
                    if not account:
                        self.server.failures.append(now)
                        return self.send(401, {"error": "Incorrect username or password"})
                    session = secrets.token_urlsafe(32)
                    self.server.sessions = {key: record for key, record in self.server.sessions.items() if record["expires"] > now}
                    self.server.sessions[session] = {"expires": now + 43200, "account_id": account["id"], "version": account["version"]}
                return self.send(200, {"ok": True, "user": self.server.accounts.public(account)}, cookie=self.session_cookie(session, 43200))
            if not self.authenticated():
                return self.send(401, {"error": "Sign in to continue"})
            if path == "/api/logout":
                cookie = SimpleCookie(self.headers.get("Cookie", ""))
                with self.server.auth_lock:
                    if cookie.get("session"):
                        self.server.sessions.pop(cookie["session"].value, None)
                return self.send(200, {"ok": True}, cookie=self.session_cookie("", 0))
            with self.server.operations:
                user = self.current_user()
                if not user:
                    return self.send(401, {"error": "Sign in to continue"})
                manager = self.server.manager
                pieces = path.strip("/").split("/")
                if path == "/api/accounts" or (len(pieces) == 4 and pieces[1] == "accounts"):
                    if user["role"] != "admin":
                        raise PermissionError("Administrator access required")
                    if path == "/api/accounts":
                        return self.send(201, {"account": self.server.accounts.save(payload)})
                    if pieces[3] == "save":
                        return self.send(200, {"account": self.server.accounts.save(payload, pieces[2])})
                    if pieces[3] == "delete":
                        self.server.accounts.delete(pieces[2])
                        return self.send(200, {"ok": True})
                    return self.send(404, {"error": "Route not found"})
                if path == "/api/bots":
                    self.require(user, "bots.create")
                    bot_id = manager.save_bot(payload)
                    self.server.accounts.grant_created_bot(user["id"], bot_id)
                    return self.send(201, {"id": bot_id})
                if path == "/api/import":
                    self.require(user, "bots.import")
                    bot_id = manager.import_bot(payload.get("path"), payload.get("python"))
                    self.server.accounts.grant_created_bot(user["id"], bot_id)
                    return self.send(201, {"id": bot_id})
                if path == "/api/cogs":
                    self.require(user, "cogs.upload")
                    manager.upload(payload.get("name"), payload.get("source"))
                elif len(pieces) == 4 and pieces[1] == "bots":
                    bot_id, action = pieces[2:]
                    permission = {"save": "configure", "start": "control", "stop": "control", "restart": "control", "delete": "delete", "cogs": "cogs"}.get(action)
                    if permission:
                        self.require(user, permission, bot_id)
                    if action == "save":
                        manager.save_bot(payload, bot_id)
                    elif action == "start":
                        manager.start(bot_id)
                    elif action == "stop":
                        manager.stop(bot_id)
                    elif action == "restart":
                        manager.stop(bot_id)
                        manager.start(bot_id)
                    elif action == "delete":
                        manager.delete(bot_id)
                    elif action == "cogs":
                        manager.cog_action(bot_id, payload.get("module"), payload.get("action"))
                    else:
                        return self.send(404, {"error": "Route not found"})
                elif len(pieces) == 5 and pieces[1] == "bots" and pieces[3] == "settings":
                    self.require(user, "settings.write", pieces[2])
                    if "settings" not in payload or not isinstance(payload["settings"], dict):
                        raise ValueError("Settings must be a JSON object")
                    manager.cog_settings(pieces[2], pieces[4], payload["settings"])
                else:
                    return self.send(404, {"error": "Route not found"})
            self.send(200, {"ok": True})
        except (ValueError, TypeError, KeyError) as error:
            self.send(400, {"error": str(error)})
        except PermissionError as error:
            self.send(403, {"error": str(error)})
        except Exception:
            self.send(500, {"error": "Internal error; check the server terminal"})
            import traceback
            traceback.print_exc()


def main():
    load_env(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Local bot manager portal")
    parser.add_argument("--port", type=int, default=int(os.environ.get("BOTMANAGER_PORT", "8765")))
    parser.add_argument("--reset-password", metavar="USERNAME", help="Reset an account password locally, with hidden prompts")
    args = parser.parse_args()
    password = os.environ.get("BOTMANAGER_PASSWORD") or secrets.token_urlsafe(18)
    manager = Manager()
    if args.reset_password:
        accounts = Accounts(manager.data_dir / "accounts.json", password, os.environ.get("BOTMANAGER_ADMIN_USERNAME", "admin"))
        account = next((a for a in accounts.store.read()["accounts"] if a["username"].casefold() == args.reset_password.casefold()), None)
        if not account:
            parser.error("Account not found")
        new_password = getpass.getpass("New password: ")
        if new_password != getpass.getpass("Confirm password: "):
            parser.error("Passwords do not match")
        try:
            if not new_password:
                raise ValueError("A new password is required")
            accounts.save({"password": new_password}, account["id"])
        except ValueError as error:
            parser.error(str(error))
        print("Password reset. Existing sessions for that account are revoked.")
        return
    server = Portal(("127.0.0.1", args.port), manager, password, os.environ.get("BOTMANAGER_PUBLIC_URL"), os.environ.get("BOTMANAGER_ADMIN_USERNAME", "admin"))
    print(f"\nBotManager: http://127.0.0.1:{server.server_address[1]}\nSign in with your account.\nPress Ctrl+C to stop the portal and all bots.\n", flush=True)
    if server.accounts.created_admin:
        print(f"Initial admin username: {server.accounts.bootstrap_username}\nInitial admin password: {password}\nManage accounts at /admin.\n", flush=True)
    if server.public_origin:
        print(f"Public URL (through Caddy): {server.public_origin}\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.shutdown()
