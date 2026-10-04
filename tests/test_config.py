import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from botmanager.config import load_env, public_origin, normalize_co_owners, red_launch_args


class ConfigTests(unittest.TestCase):
    def test_explicit_redbot_co_owner_arguments(self):
        self.assertEqual(normalize_co_owners('713265432383193159, 123 123'), ['713265432383193159', '123'])
        self.assertEqual(red_launch_args({'id': 'example', 'red_co_owner_ids': ['713265432383193159']}),
                         ['redbot', 'example', '--no-prompt', '--co-owner', '713265432383193159'])
        self.assertEqual(red_launch_args({'id': 'example'}), ['redbot', 'example', '--no-prompt'])
        for invalid in ('--team-members-are-owners', '0', '-1', str(2**64), [True], {}):
            with self.assertRaises(ValueError):
                normalize_co_owners(invalid)
    def test_literal_env_loading_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text('# comment\nSETTING_ONE="hello # literal"\nSETTING_TWO=value=with=equals\nSETTING_THREE=\n', encoding="utf-8")
            with patch.dict(os.environ, {"SETTING_ONE": "existing"}, clear=True):
                load_env(path)
                self.assertEqual(os.environ["SETTING_ONE"], "existing")
                self.assertEqual(os.environ["SETTING_TWO"], "value=with=equals")
                self.assertEqual(os.environ["SETTING_THREE"], "")

    def test_public_url_validation(self):
        self.assertIsNone(public_origin(""))
        self.assertEqual(public_origin("https://bots.eclipted.com/"), "https://bots.eclipted.com")
        self.assertEqual(public_origin("https://bots.eclipted.com:443"), "https://bots.eclipted.com")
        for value in ("http://bots.eclipted.com", "https://user:pass@bots.eclipted.com", "https://bots.eclipted.com/path", "https://bots.eclipted.com?query=1"):
            with self.assertRaises(ValueError):
                public_origin(value)
