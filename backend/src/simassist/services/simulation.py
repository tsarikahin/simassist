from __future__ import annotations

from typing import cast

from simassist.core.capabilities import Capability
from simassist.core.models.geometry import (
    GeometryResult,
    GeometrySpec,
)
from simassist.core.models.mesh import MeshRequest, MeshResult
from simassist.core.registry import EngineRegistry
from simassist.simulation.geometry.base import GeometryEngine
from simassist.simulation.meshing.base import MeshingEngine


class SimulationService:
    """Engine-independent simulation operations."""

    def __init__(self, registry: EngineRegistry):
        self.registry = registry

    def _resolve_engine(
        self,
        capability: Capability,
        engine_key: str | None,
    ) -> object:
        available = self.registry.find_by_capability(capability)

        if engine_key is None:
            if len(available) != 1:
                raise ValueError(
                    f"Specify an engine for {capability.value}. "
                    f"Available engines: {available}"
                )
            engine_key = available[0]

        if engine_key not in available:
            raise ValueError(
                f"Engine '{engine_key}' does not support "
                f"'{capability.value}'. Available: {available}"
            )

        return self.registry.get(engine_key)

    def create_geometry(
        self,
        spec: GeometrySpec,
        engine_key: str | None = None,
    ) -> GeometryResult:
        engine = cast(
            GeometryEngine,
            self._resolve_engine(
                Capability.GEOMETRY_CREATE,
                engine_key,
            ),
        )

        return engine.create(spec)

    def inspect_geometry(
        self,
        geometry: GeometryResult,
        engine_key: str | None = None,
    ):
        engine = cast(
            GeometryEngine,
            self._resolve_engine(
                Capability.GEOMETRY_INSPECT,
                engine_key or f"{geometry.engine}.geometry",
            ),
        )

        return engine.inspect(geometry)

    def generate_mesh(
        self,
        request: MeshRequest,
        engine_key: str | None = None,
    ) -> MeshResult:
        engine = cast(
            MeshingEngine,
            self._resolve_engine(
                Capability.MESH_GENERATE,
                engine_key,
            ),
        )

        return engine.generate(request)
