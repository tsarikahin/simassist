from enum import StrEnum

from pydantic import BaseModel, Field


class Capability(StrEnum):
    GEOMETRY_CREATE = "geometry.create"
    GEOMETRY_INSPECT = "geometry.inspect"
    MESH_GENERATE = "mesh.generate"
    STRUCTURAL_STATIC = "solver.structural.static"
    STRUCTURAL_NONLINEAR = "solver.structural.nonlinear"
    THERMAL = "solver.thermal"


class EngineDescriptor(BaseModel):
    name: str
    capabilities: set[Capability] = Field(default_factory=set)
    description: str = ""


class CapabilityInfo(BaseModel):
    capability: Capability
    engines: list[str]
