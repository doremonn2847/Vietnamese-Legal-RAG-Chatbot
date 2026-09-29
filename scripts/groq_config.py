"""Known-key direct Groq configuration; disabled unless explicitly enabled."""
import os
from pathlib import Path

from groq import GroqConfig, GroqProvider, http_transport

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_ROUTE = "chat/completions"
GROQ_MODEL = "openai/gpt-oss-20b"
_KEYS = {"GROQ_API_KEY", "GROQ_ENABLED", "GROQ_BASE_URL", "GROQ_ROUTE", "GROQ_MODEL"}


def load_config(env=None, dotenv_path=".env"):
    values = {**_dotenv(dotenv_path), **(dict(env) if env is not None else os.environ)}
    config = GroqConfig(values.get("GROQ_BASE_URL"), values.get("GROQ_ROUTE"), values.get("GROQ_MODEL"), values.get("GROQ_ENABLED", "").casefold() == "true")
    if not config.enabled: return config, None
    if config.base_url != GROQ_BASE_URL or config.route != GROQ_ROUTE or config.model != GROQ_MODEL or not values.get("GROQ_API_KEY", "").strip(): raise ValueError("invalid enabled Groq configuration")
    config.validate()
    return config, values["GROQ_API_KEY"]


def create_runtime_app(env=None, dotenv_path=".env"):
    config, key = load_config(env, dotenv_path)
    from app import create_app
    return create_app() if not config.enabled else create_app(GroqProvider(config, http_transport(), key))


def _dotenv(path):
    file, values = Path(path), {}
    if not file.exists(): return values
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"): continue
        if "=" not in line: raise ValueError("invalid dotenv line")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in _KEYS: continue
        if key in values: raise ValueError("duplicate dotenv key")
        if value.startswith(("'", '"')) or value.endswith(("'", '"')): raise ValueError("quoted dotenv values are unsupported")
        values[key] = value
    return values
