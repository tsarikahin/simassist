from __future__ import annotations

from typing import Any

from simassist.core.capabilities import (
    Capability,
    EngineDescriptor,
)


class EngineRegistry:
    """Registry for simulation engine implementations."""

    def __init__(self):
        self._engines: dict[str, Any] = {}
        self._descriptors: dict[str, EngineDescriptor] = {}

    def register(
        self,
        key: str,
        engine: Any,
        descriptor: EngineDescriptor,
    ) -> None:
        if key in self._engines:
            raise ValueError(f"Engine already registered: {key}")

        self._engines[key] = engine
        self._descriptors[key] = descriptor

    def get(self, key: str) -> Any:
        if key not in self._engines:
            raise KeyError(f"Unknown engine: {key}")

        return self._engines[key]

    def find_by_capability(
        self,
        capability: Capability,
    ) -> list[str]:
        return [
            key
            for key, descriptor in self._descriptors.items()
            if capability in descriptor.capabilities
        ]

    def list_engines(self) -> list[EngineDescriptor]:
        return list(self._descriptors.values())
