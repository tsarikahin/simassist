from typing import Protocol

from simassist.core.models.mesh import MeshRequest, MeshResult


class MeshingEngine(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, request: MeshRequest) -> MeshResult: ...
