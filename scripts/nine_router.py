"""Disabled-by-default 9Router HTTP contract; never discovers credentials or probes."""
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class NineRouterConfig:
    base_url: str | None = None
    route: str | None = None
    model: str | None = None
    enabled: bool = False

    def validate(self):
        if self.enabled and (not self.base_url or not self.route or not self.model):
            raise ValueError("enabled 9Router requires explicit base_url, route, and model")


class NineRouterProvider:
    def __init__(self, config, transport, api_key=None):
        config.validate()
        self.config, self.transport, self.api_key = config, transport, api_key

    def generate(self, messages):
        if not self.config.enabled:
            raise RuntimeError("9Router is disabled")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        response = self.transport("POST", self.config.base_url.rstrip("/") + "/" + self.config.route.lstrip("/"), {"model": self.config.model, "messages": messages}, headers)
        content = response["choices"][0]["message"]["content"]
        return {"content": content, "usage": response.get("usage")}
