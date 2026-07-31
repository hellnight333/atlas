from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class ProviderAdapter(ABC):
    @abstractmethod
    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        pass


class LocalFluxProvider(ProviderAdapter):
    name = "local-flux"

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Simulate local GPU execution for the demo.
        # Replace this stub with real model inference when GPUs are available.
        time.sleep(0.75)
        if action == "image.generate":
            prompt = payload.get("prompt", "Atlas generated image")
            return {"result": "image_generated", "prompt": prompt, "uri": f"https://example.com/generated/{hash(prompt) % 10000}"}
        return {"result": "ok", "action": action, "payload": payload}


class LocalTextProvider(ProviderAdapter):
    name = "local-text"

    def execute(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.4)
        prompt = payload.get("prompt", "Atlas generated text")
        if action == "text.generate":
            return {"result": "text_generated", "prompt": prompt, "text": f"Generated response for: {prompt}"}
        if action == "code.generate":
            return {
                "result": "code_generated",
                "prompt": prompt,
                "language": payload.get("language", "python"),
                "code": f"# Generated code for: {prompt}\nprint('Atlas code output')",
            }
        return {"result": "ok", "action": action, "payload": payload}


@dataclass
class ProviderManager:
    adapters: dict[str, ProviderAdapter] = None

    def __post_init__(self) -> None:
        if self.adapters is None:
            self.adapters = {}

    def register_adapter(self, name: str, adapter: ProviderAdapter) -> None:
        self.adapters[name] = adapter

    def get_adapter(self, name: str) -> ProviderAdapter | None:
        return self.adapters.get(name)
