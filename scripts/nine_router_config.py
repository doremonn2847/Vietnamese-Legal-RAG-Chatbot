"""Known-key local 9Router config; no discovery and no fallback."""
import os
from urllib.parse import urlparse
from nine_router import NineRouterConfig


def load_config(env=None):
    values = dict(env or os.environ)
    config = NineRouterConfig(values.get("NINE_ROUTER_BASE_URL"), values.get("NINE_ROUTER_ROUTE"), values.get("NINE_ROUTER_MODEL"), values.get("NINE_ROUTER_ENABLED", "").casefold() == "true")
    if not config.enabled:
        return config, None
    parsed = urlparse(config.base_url or "")
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or config.route != "chat/completions" or config.model != "ragchatbot" or not values.get("NINE_ROUTER_API_KEY", "").strip():
        raise ValueError("invalid enabled local 9Router configuration")
    config.validate()
    return config, values["NINE_ROUTER_API_KEY"]
