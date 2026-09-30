import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from groq_config import create_runtime_app, load_config


class GroqConfigTest(unittest.TestCase):
    def test_disabled_default_and_exact_allowlist(self):
        self.assertFalse(load_config({}, "missing.env")[0].enabled)
        env = {"GROQ_ENABLED":"true", "GROQ_API_KEY":"secret", "GROQ_BASE_URL":"https://api.groq.com/openai/v1", "GROQ_ROUTE":"chat/completions", "GROQ_MODEL":"openai/gpt-oss-20b"}
        self.assertTrue(load_config(env, "missing.env")[0].enabled)
        for key, value in (("GROQ_API_KEY", ""), ("GROQ_BASE_URL", "https://other.invalid"), ("GROQ_ROUTE", "other"), ("GROQ_MODEL", "paid")):
            with self.subTest(key=key), self.assertRaises(ValueError): load_config({**env, key: value}, "missing.env")
        self.assertNotIn("secret", str(TestClient(create_runtime_app(env, "missing.env")).get("/health").json()))

    def test_dotenv_known_keys_only_and_factory_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"; path.write_text("GROQ_ENABLED=false\n", encoding="utf-8")
            self.assertTrue(load_config({"GROQ_ENABLED":"true", "GROQ_API_KEY":"x", "GROQ_BASE_URL":"https://api.groq.com/openai/v1", "GROQ_ROUTE":"chat/completions", "GROQ_MODEL":"openai/gpt-oss-20b"}, path)[0].enabled)
            path.write_text("bad\n", encoding="utf-8")
            with self.assertRaises(ValueError): load_config({}, path)
        self.assertTrue(TestClient(create_runtime_app({"GROQ_ENABLED":"false"}, "missing.env")).get("/health").json()["demo"])
        with self.assertRaises(ValueError): create_runtime_app({"GROQ_ENABLED":"true"}, "missing.env")

    def test_rejects_embedded_key_assignment_without_disclosing_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("GROQ_ENABLED=false\nGROQ_API_KEY=groq-placeholderQDRANT_API_KEY=qdrant-placeholder\nQDRANT_API_KEY=separate-placeholder\n", encoding="utf-8")
            with self.assertRaises(ValueError) as caught:
                load_config({}, path)
            self.assertNotIn("placeholder", str(caught.exception))
        with self.assertRaises(ValueError) as caught:
            load_config({"GROQ_ENABLED":"false", "GROQ_API_KEY":"groq-placeholderQDRANT_API_KEY=qdrant-placeholder"}, "missing.env")
        self.assertNotIn("placeholder", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
