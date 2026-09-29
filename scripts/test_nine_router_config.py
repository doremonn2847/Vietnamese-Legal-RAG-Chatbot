import unittest
import tempfile
from pathlib import Path
from nine_router_config import load_config


class ConfigTest(unittest.TestCase):
    def test_enabled_config_is_exact_loopback_only(self):
        env = {"NINE_ROUTER_ENABLED":"true","NINE_ROUTER_API_KEY":"x","NINE_ROUTER_BASE_URL":"http://127.0.0.1:20128/v1","NINE_ROUTER_ROUTE":"chat/completions","NINE_ROUTER_MODEL":"ragchatbot"}
        self.assertTrue(load_config(env)[0].enabled)
        for key, value in (("NINE_ROUTER_API_KEY", ""), ("NINE_ROUTER_BASE_URL", "http://example.com"), ("NINE_ROUTER_ROUTE", "other"), ("NINE_ROUTER_MODEL", "other")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                load_config({**env, key:value})

    def test_dotenv_precedence_and_invalid_lines_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"; path.write_text("NINE_ROUTER_ENABLED=false\n", encoding="utf-8")
            self.assertTrue(load_config({"NINE_ROUTER_ENABLED":"true","NINE_ROUTER_API_KEY":"x","NINE_ROUTER_BASE_URL":"http://127.0.0.1:20128/v1","NINE_ROUTER_ROUTE":"chat/completions","NINE_ROUTER_MODEL":"ragchatbot"}, path)[0].enabled)
            path.write_text("bad\n", encoding="utf-8")
            with self.assertRaises(ValueError): load_config({}, path)
