from __future__ import annotations

from typing import Protocol, runtime_checkable

from simassist.core.models.geometry import (
    GeometryMetadata,
    GeometryResult,
    GeometrySpec,
)


@runtime_checkable
class GeometryEngine(Protocol):
    """Common interface for geometry engines."""

    @property
    def name(self) -> str:
        """Unique engine identifier."""
        ...

    def create(self, spec: GeometrySpec) -> GeometryResult:
        """Create geometry from an engine-independent specification."""
        ...

    def inspect(self, geometry: GeometryResult) -> GeometryMetadata:
        """Inspect an existing geometry artifact."""
        ...
