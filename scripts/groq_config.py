"""Known-key direct Groq configuration; disabled unless explicitly enabled."""
import os
from pathlib import Path
import re

from groq import GROQ_BASE_URL, GROQ_MODEL, GROQ_ROUTE, GroqConfig, GroqProvider, http_transport
_KEYS = {"GROQ_API_KEY", "GROQ_ENABLED", "GROQ_BASE_URL", "GROQ_ROUTE", "GROQ_MODEL"}
_EMBEDDED_KEY_ASSIGNMENT = re.compile(r"[A-Z][A-Z0-9_]*_API_KEY\s*=")


def load_config(env=None, dotenv_path=".env"):
    values = {**_dotenv(dotenv_path), **(dict(env) if env is not None else os.environ)}
    if any(key.endswith("_API_KEY") and isinstance(value, str) and _EMBEDDED_KEY_ASSIGNMENT.search(value)
           for key, value in values.items()):
        raise ValueError("credential value contains an embedded key assignment")
    config = GroqConfig(values.get("GROQ_BASE_URL"), values.get("GROQ_ROUTE"), values.get("GROQ_MODEL"), values.get("GROQ_ENABLED", "").casefold() == "true")
    if not config.enabled: return config, None
    config.validate(values.get("GROQ_API_KEY"))
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
