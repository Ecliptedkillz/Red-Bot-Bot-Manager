import json
import sys
import tempfile
import unittest
from pathlib import Path

from botmanager.manager import Manager
from botmanager.storage import JsonStore


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.source = root / "legacy"
        (self.source / "core").mkdir(parents=True)
        package = self.source / "cogs" / "CogManager" / "cogs" / "welcome"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("async def setup(bot): pass", encoding="utf-8")
        JsonStore(self.source / "core" / "settings.json").write({"0": {"GLOBAL": {"token": "test-token", "prefix": ["-", "!"], "packages": ["welcome"], "owner": 123}}})
        JsonStore(self.source / "cogs" / "Welcome" / "settings.json").write({"123": {"GLOBAL": {"message": "Original", "path": str(package)}}})
        self.manager = Manager(root / "managed")

    def tearDown(self):
        self.manager.shutdown()
        self.temp.cleanup()

    def test_full_copy_metadata_and_source_preservation(self):
        bot_id = self.manager.import_bot(str(self.source), sys.executable)
        bot = self.manager.bot(bot_id)
        self.assertEqual(bot["mode"], "redbot")
        self.assertEqual(bot["prefix"], "-")
        self.assertEqual(bot["enabled_cogs"], ["welcome"])
        self.assertEqual(self.manager.snapshot()["bots"][0]["status"], "stopped")
        self.assertNotIn("test-token", json.dumps(self.manager.snapshot()))
        self.assertTrue((Path(bot["red_data"]) / "cogs/CogManager/cogs/welcome/__init__.py").exists())
        data = self.manager.cog_settings(bot_id, "config:Welcome")
        self.assertTrue(data["123"]["GLOBAL"]["path"].startswith(bot["red_data"]))
        data["123"]["GLOBAL"]["message"] = "Edited"
        self.manager.cog_settings(bot_id, "config:Welcome", data)
        original = JsonStore(self.source / "cogs/Welcome/settings.json").read()
        self.assertEqual(original["123"]["GLOBAL"]["message"], "Original")
        self.manager.save_bot({"name": "Renamed", "prefix": "$"}, bot_id)
        updated = self.manager.bot(bot_id)
        self.assertEqual(updated["red_data"], bot["red_data"])
        self.assertEqual(JsonStore(Path(bot["red_data"]) / "core/settings.json").read()["0"]["GLOBAL"]["prefix"], ["$"])
        self.assertEqual(JsonStore(self.source / "core/settings.json").read()["0"]["GLOBAL"]["prefix"], ["-", "!"])
        with self.assertRaisesRegex(ValueError, "already imported"):
            self.manager.import_bot(str(self.source), sys.executable)

    def test_reject_invalid_imports_and_runtime_conversion(self):
        with self.assertRaisesRegex(ValueError, "core/settings.json"):
            self.manager.import_bot(self.temp.name, sys.executable)
        with self.assertRaisesRegex(ValueError, "Python executable"):
            self.manager.import_bot(str(self.source), str(self.source / "missing.exe"))
        bot_id = self.manager.import_bot(str(self.source), sys.executable)
        with self.assertRaisesRegex(ValueError, "native runtime"):
            self.manager.save_bot({"mode": "discord"}, bot_id)
        with self.assertRaises(ValueError):
            self.manager.cog_settings(bot_id, "config:../../core")
        with self.assertRaises(ValueError):
            self.manager.cog_action(bot_id, "config:Welcome", "load")
        with self.assertRaises(ValueError):
            self.manager.save_bot({"name": "Fake", "mode": "redbot"})


if __name__ == "__main__":
    unittest.main()
