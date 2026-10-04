import http.client
import json
import tempfile
import unittest
from pathlib import Path

from botmanager.accounts import Accounts, allowed
import test_manager


class AccountTests(unittest.TestCase):
    def test_password_hashes_bootstrap_and_last_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "accounts.json"
            accounts = Accounts(path, "initial-password")
            self.assertNotIn("initial-password", path.read_text())
            admin = accounts.authenticate("admin", "initial-password")
            self.assertIsNotNone(admin)
            self.assertNotIn("password_hash", accounts.public(admin))
            for change in ({"disabled": True}, {"role": "member"}):
                with self.assertRaisesRegex(ValueError, "administrator"):
                    accounts.save(change, admin["id"])
            with self.assertRaisesRegex(ValueError, "administrator"):
                accounts.delete(admin["id"])
            accounts.save({"password": "replacement-password"}, admin["id"])
            restarted = Accounts(path, "initial-password")
            self.assertIsNone(restarted.authenticate("admin", "initial-password"))
            self.assertIsNotNone(restarted.authenticate("ADMIN", "replacement-password"))
            for payload in ({"username": "user", "password": "short"},
                            {"username": "user", "password": "valid-password", "site_permissions": ["anything"]},
                            {"username": "user", "password": "valid-password", "bot_permissions": {"../../escape": ["view"]}}):
                with self.assertRaises(ValueError):
                    accounts.save(payload)

    def test_override_replaces_defaults_and_view_is_required(self):
        account = {"role": "member", "disabled": False, "site_permissions": [], "bot_defaults": ["view", "logs"],
                   "bot_permissions": {"a": [], "b": ["control"], "c": ["view", "control"]}}
        self.assertTrue(allowed(account, "logs", "other"))
        self.assertFalse(allowed(account, "view", "a"))
        self.assertFalse(allowed(account, "control", "b"))
        self.assertTrue(allowed(account, "control", "c"))
        self.assertFalse(allowed(account, "logs", "c"))


class AccountApiTests(unittest.TestCase):
    setUp = test_manager.PortalTests.setUp
    tearDown = test_manager.PortalTests.tearDown
    request = test_manager.PortalTests.request

    def login(self, username="admin", password="test-password"):
        self.cookie = None
        return self.request("/api/login", {"username": username, "password": password})[0]

    def test_site_and_bot_permissions_cannot_be_bypassed(self):
        first = self.manager.save_bot({"name": "First"})
        second = self.manager.save_bot({"name": "Second"})
        self.assertEqual(self.login(), 200)
        status, body = self.request("/api/accounts", {"username": "operator", "password": "operator-password", "bot_defaults": ["view", "logs"],
                                                    "bot_permissions": {first: ["view", "control", "cogs", "settings.read", "settings.write"], second: []}})
        self.assertEqual(status, 201)
        account_id = json.loads(body)["account"]["id"]
        self.assertNotIn(b"password_hash", body)
        self.assertEqual(self.login("operator", "operator-password"), 200)
        status, body = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual([b["id"] for b in json.loads(body)["bots"]], [first])
        self.assertNotIn(b"operator-password", body)
        for path, payload in (("/api/accounts", {}), (f"/api/accounts/{account_id}/save", {"role": "admin"}),
                              ("/api/bots", {"name": "Unauthorized"}), ("/api/import", {"path": "anything"}),
                              ("/api/cogs", {"name": "anything", "source": "async def setup(bot): pass"}),
                              (f"/api/bots/{second}/start", {}), (f"/api/bots/{first}/save", {"name": "Changed"}),
                              (f"/api/bots/{first}/delete", {})):
            self.assertEqual(self.request(path, payload)[0], 403, path)
        self.assertEqual(self.request("/api/accounts")[0], 403)
        self.assertEqual(self.request(f"/api/bots/{first}/logs")[0], 403)
        self.assertEqual(self.request(f"/api/bots/{second}/settings/cogs.general")[0], 403)
        self.assertEqual(self.request(f"/api/bots/{first}/settings/cogs.general")[0], 200)
        self.assertEqual(self.request(f"/api/bots/{first}/settings/cogs.general", {"settings": {"greeting": "Permitted"}})[0], 200)
        self.assertEqual(self.request(f"/api/bots/{first}/stop", {})[0], 200)

    def test_revocation_reset_disabled_and_permission_change(self):
        self.login()
        _, body = self.request("/api/accounts", {"username": "reader", "password": "reader-password", "bot_defaults": ["view", "logs"]})
        account_id = json.loads(body)["account"]["id"]
        admin_cookie = self.cookie
        self.assertEqual(self.login("reader", "reader-password"), 200)
        reader_cookie = self.cookie
        self.cookie = admin_cookie
        self.assertEqual(self.request(f"/api/accounts/{account_id}/save", {"password": "changed-password"})[0], 200)
        self.cookie = reader_cookie
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.login("reader", "reader-password"), 401)
        self.assertEqual(self.login("reader", "changed-password"), 200)
        reader_cookie = self.cookie
        self.cookie = admin_cookie
        self.assertEqual(self.request(f"/api/accounts/{account_id}/save", {"disabled": True})[0], 200)
        self.cookie = reader_cookie
        self.assertEqual(self.request("/api/state")[0], 401)
        self.assertEqual(self.login("reader", "changed-password"), 401)

    def test_login_never_uses_a_password_query_and_has_safe_fallback(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.port)
        connection.request("GET", "/?password=old-secret")
        response = connection.getresponse()
        self.assertEqual(response.status, 303)
        self.assertEqual(response.getheader("Location"), "/")
        self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
        response.read(); connection.close()
        _, body = self.request("/")
        self.assertIn(b'id="login-form" class="login-card" method="post" action="/api/login"', body)
        self.assertNotIn(b'src="/routes.js"', body)
        self.assertEqual(self.request("/api/state")[0], 401)
        for asset in ("/app.js", "/routes.js", "/admin.js"):
            connection = http.client.HTTPConnection("127.0.0.1", self.port)
            connection.request("GET", asset)
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(response.getheader("Content-Type").startswith("application/javascript"))
            response.read(); connection.close()

    def test_member_creating_bot_gets_only_that_bot(self):
        self.manager.save_bot({"name": "Private"})
        self.login()
        self.request("/api/accounts", {"username": "creator", "password": "creator-password", "site_permissions": ["bots.create"]})
        self.login("creator", "creator-password")
        status, body = self.request("/api/bots", {"name": "Mine"})
        self.assertEqual(status, 201)
        created = json.loads(body)["id"]
        state = json.loads(self.request("/api/state")[1])
        self.assertEqual([b["id"] for b in state["bots"]], [created])
        self.assertIn("control", state["bots"][0]["permissions"])
