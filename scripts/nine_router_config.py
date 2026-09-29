"""Known-key local 9Router config; no discovery and no fallback."""
import os
from urllib.parse import urlparse
from pathlib import Path
from nine_router import NineRouterConfig, NineRouterProvider, http_transport


def load_config(env=None, dotenv_path=".env"):
    values = {**_dotenv(dotenv_path), **(dict(env) if env is not None else os.environ)}
    config = NineRouterConfig(values.get("NINE_ROUTER_BASE_URL"), values.get("NINE_ROUTER_ROUTE"), values.get("NINE_ROUTER_MODEL"), values.get("NINE_ROUTER_ENABLED", "").casefold() == "true")
    if not config.enabled:
        return config, None
    parsed = urlparse(config.base_url or "")
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or config.route != "chat/completions" or config.model != "ragchatbot" or not values.get("NINE_ROUTER_API_KEY", "").strip():
        raise ValueError("invalid enabled local 9Router configuration")
    config.validate()
    return config, values["NINE_ROUTER_API_KEY"]


def create_runtime_app(env=None, dotenv_path=".env"):
    config, key = load_config(env, dotenv_path)
    from app import create_app
    return create_app() if not config.enabled else create_app(NineRouterProvider(config, http_transport(), key))


def _dotenv(path):
    file, values = Path(path), {}
    if not file.exists(): return values
    for line in file.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#"): continue
        if "=" not in line: raise ValueError("invalid dotenv line")
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in {"NINE_ROUTER_API_KEY", "NINE_ROUTER_ENABLED", "NINE_ROUTER_BASE_URL", "NINE_ROUTER_ROUTE", "NINE_ROUTER_MODEL"}: continue
        if key in values: raise ValueError("duplicate dotenv key")
        if value.startswith(("'", '"')) or value.endswith(("'", '"')): raise ValueError("quoted dotenv values are unsupported")
        values[key] = value
    return values
