import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from botmanager.manager import Manager
from botmanager.server import Portal
from botmanager.storage import JsonStore


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Manager(self.temp.name)
        self.bot_id = self.manager.save_bot({"name": "Test bot", "mode": "demo", "prefix": "!"})

    def tearDown(self):
        self.manager.shutdown()
        for process in self.manager.processes.values():
            process.stdin.close()
            process.stdout.close()
        self.temp.cleanup()

    def wait_running(self):
        deadline = time.time() + 5
        while time.time() < deadline:
            if self.manager.snapshot()["bots"][0]["status"] == "running":
                return
            time.sleep(.03)
        self.fail("Demo process never became ready")

    def test_lifecycle_and_cog_persistence(self):
        self.manager.start(self.bot_id)
        self.wait_running()
        with self.assertRaisesRegex(ValueError, "already running"):
            self.manager.start(self.bot_id)
        self.manager.cog_action(self.bot_id, "cogs.moderation", "load")
        self.manager.cog_action(self.bot_id, "cogs.moderation", "reload")
        self.manager.cog_action(self.bot_id, "cogs.general", "unload")
        with self.assertRaisesRegex(ValueError, "not loaded"):
            self.manager.cog_action(self.bot_id, "cogs.general", "reload")
        with self.assertRaisesRegex(ValueError, "Stop the bot"):
            self.manager.save_bot({"name": "New name"}, self.bot_id)
        self.manager.stop(self.bot_id)
        self.assertEqual(self.manager.snapshot()["bots"][0]["status"], "stopped")
        self.manager.start(self.bot_id)
        self.wait_running()
        self.assertEqual(self.manager.snapshot()["bots"][0]["loaded"], ["cogs.moderation"])

    def test_upload_and_settings(self):
        self.manager.upload("welcome", "async def setup(bot):\n    pass\n")
        self.assertIn("custom_cogs.welcome", {c["module"] for c in self.manager.cogs()})
        for name in ("../escape", "BadName", "../../secrets"):
            with self.assertRaises(ValueError):
                self.manager.upload(name, "async def setup(bot): pass")
        with self.assertRaisesRegex(ValueError, "syntax error"):
            self.manager.upload("invalid", "async def setup(:")
        with self.assertRaisesRegex(ValueError, "async def setup"):
            self.manager.upload("invalid", "x = 1")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.manager.upload("welcome", "async def setup(bot): pass")
        self.manager.cog_settings(self.bot_id, "custom_cogs.welcome", {"message": "Hi", "nested": {"enabled": True}})
        fresh = Manager(self.temp.name)
        self.assertEqual(fresh.cog_settings(self.bot_id, "custom_cogs.welcome")["message"], "Hi")
        with self.assertRaises(ValueError):
            self.manager.cog_settings(self.bot_id, "../../escape", {})

    def test_delete_running_bot_and_shutdown(self):
        self.manager.start(self.bot_id)
        self.wait_running()
        process = self.manager.processes[self.bot_id]
        self.manager.delete(self.bot_id)
        self.assertIsNotNone(process.poll())
        self.assertEqual(self.manager.snapshot()["bots"], [])
        self.manager.shutdown()

    def test_tokens_hidden_and_redacted(self):
        self.manager.save_bot({"token": "secret-token"}, self.bot_id)
        self.manager.log(self.bot_id, "Failure secret-token")
        self.assertNotIn("secret-token", json.dumps(self.manager.snapshot()))
        self.assertNotIn("secret-token", json.dumps(list(self.manager.logs[self.bot_id])))
        self.assertTrue(self.manager.snapshot()["bots"][0]["has_token"])

    def test_storage_concurrent_updates(self):
        store = JsonStore(Path(self.temp.name) / "counter.json", {"count": 0})
        def increment():
            for _ in range(20):
                store.update(lambda value: value.update(count=value["count"] + 1))
        threads = [threading.Thread(target=increment) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(store.read()["count"], 80)


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.manager = Manager(self.temp.name)
        self.server = Portal(("127.0.0.1", 0), self.manager, "test-password")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]
        self.cookie = None

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.manager.shutdown()
        self.thread.join()
        self.temp.cleanup()

    def request(self, path, payload=None, origin=True, host=None, extra_headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port)
        headers = {"Host": host or f"127.0.0.1:{self.port}"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if payload is not None:
            headers["Content-Type"] = "application/json"
            if origin:
                headers["Origin"] = origin if isinstance(origin, str) else f"http://127.0.0.1:{self.port}"
        headers.update(extra_headers or {})
        conn.request("GET" if payload is None else "POST", path, None if payload is None else json.dumps(payload), headers)
        response = conn.getresponse()
        cookie = response.getheader("Set-Cookie")
        self.last_cookie_header = cookie
        if cookie:
            self.cookie = cookie.split(";")[0]
        body = response.read()
        status = response.status
        conn.close()
        return status, body

    def test_auth_origin_and_host(self):
        self.assertEqual(self.request("/api/session")[0], 200)
        self.assertFalse(json.loads(self.request("/api/session")[1])["authenticated"])
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)

        self.assertEqual(self.request("/api/login", {"password": "test-password"}, origin=False)[0], 403)
        self.assertEqual(self.request("/api/login", {"password": "wrong"})[0], 401)
        self.assertEqual(self.request("/api/login", {"password": "test-password"})[0], 200)
        self.assertTrue(json.loads(self.request("/api/session")[1])["authenticated"])
        self.assertEqual(self.request("/api/state", host="evil.example")[0], 403)
        self.assertEqual(self.request("/api/state")[0], 200)
        self.assertEqual(self.request("/api/bots", {"name": "Demo"}, origin=False)[0], 403)
        status, body = self.request("/api/bots", {"name": "Demo"})
        self.assertEqual(status, 201)
        bot_id = json.loads(body)["id"]
        self.assertEqual(self.request(f"/api/bots/{bot_id}/settings/cogs.general", {"settings": []})[0], 400)
        self.assertEqual(self.request(f"/api/bots/{bot_id}/settings/cogs.general", {"settings": {"greeting": "Hello"}})[0], 200)
        self.assertEqual(json.loads(self.request(f"/api/bots/{bot_id}/settings/cogs.general")[1])["settings"], {"greeting": "Hello"})
        self.assertEqual(self.request("/api/logout", {})[0], 200)
        self.assertEqual(self.request("/api/state")[0], 401)

    def test_bookmarked_portal_pages_and_asset_boundaries(self):
        for path in ('/cogs', '/logs', '/bots/new', '/bots/import', '/cogs/new',
                     '/bots/58484bb5e23a', '/bots/58484bb5e23a/console',
                     '/bots/58484bb5e23a/cogs', '/bots/58484bb5e23a/settings',
                     '/bots/58484bb5e23a/cogs/config%3AScamShield/settings'):
            status, body = self.request(path)
            self.assertEqual(status, 200, path)
            self.assertIn(b'<!doctype html>', body)
            self.assertIn(b'src="/app.js"', body)
            self.assertNotIn(b'src="/routes.js"', body)
        self.assertEqual(self.request('/routes.js')[0], 200)
        self.assertEqual(self.request('/admin.js')[0], 200)
        self.assertEqual(self.request('/admin')[0], 200)
        self.assertEqual(self.request('/data/bots.json')[0], 404)
        self.assertEqual(self.request('/unknown')[0], 404)
        self.assertEqual(self.request('/api/state')[0], 401)


    def test_public_https_login_and_secure_cookie(self):
        self.server.public_origin = "https://bots.eclipted.com"
        self.assertEqual(self.request("/", host="bots.eclipted.com")[0], 200)
        self.assertEqual(self.request("/api/login", {"password": "test-password"},
                                      host="bots.eclipted.com", origin="http://bots.eclipted.com")[0], 403)
        self.assertEqual(self.request("/api/login", {"password": "test-password"},
                                      host="bots.eclipted.com", origin="https://evil.example")[0], 403)
        self.assertEqual(self.request("/api/login", {"password": "test-password"},
                                      host="bots.eclipted.com", origin="https://bots.eclipted.com")[0], 200)
        self.assertIn("; Secure", self.last_cookie_header)
        self.assertEqual(self.request("/api/state", host="bots.eclipted.com")[0], 200)
        self.assertEqual(self.request("/api/logout", {}, host="bots.eclipted.com",
                                      origin="https://bots.eclipted.com")[0], 200)
        self.assertIn("; Secure", self.last_cookie_header)
        self.assertEqual(self.request("/api/state", host="evil.example",
                                      extra_headers={"X-Forwarded-Host": "bots.eclipted.com"})[0], 403)
        self.assertEqual(self.request("/api/login", {"password": "test-password"})[0], 200)
        self.assertNotIn("; Secure", self.last_cookie_header)


if __name__ == "__main__":
    unittest.main()
