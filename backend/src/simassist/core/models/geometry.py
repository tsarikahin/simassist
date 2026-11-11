from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class LengthUnit(StrEnum):
    MM = "mm"
    CM = "cm"
    M = "m"
    INCH = "in"


class Vector3D(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class GeometrySource(StrEnum):
    PRIMITIVE = "primitive"
    CAD_IMPORT = "cad_import"
    OPERATIONS = "operations"


class PrimitiveType(StrEnum):
    BOX = "box"
    CYLINDER = "cylinder"
    SPHERE = "sphere"


class PrimitiveGeometry(BaseModel):
    source: Literal["primitive"] = "primitive"
    primitive: PrimitiveType
    parameters: dict[str, float]
    origin: Vector3D = Field(default_factory=Vector3D)


class CADImportGeometry(BaseModel):
    source: Literal["cad_import"] = "cad_import"
    artifact_id: UUID


class BooleanOperation(StrEnum):
    UNION = "union"
    DIFFERENCE = "difference"
    INTERSECTION = "intersection"


class BooleanGeometry(BaseModel):
    source: Literal["operations"] = "operations"
    operation: BooleanOperation
    operands: list[UUID] = Field(min_length=2)


GeometryDefinition = Annotated[
    PrimitiveGeometry | CADImportGeometry | BooleanGeometry,
    Field(discriminator="source"),
]


class GeometrySpec(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    units: LengthUnit = LengthUnit.MM
    definition: GeometryDefinition


class GeometryCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    units: LengthUnit = LengthUnit.MM
    definition: GeometryDefinition


class GeometryMetadata(BaseModel):
    volume_count: int = Field(default=0, ge=0)
    surface_count: int = Field(default=0, ge=0)
    bounding_box_min: Vector3D | None = None
    bounding_box_max: Vector3D | None = None


class GeometryResult(BaseModel):
    geometry_id: UUID
    engine: str
    artifact_id: UUID
    metadata: GeometryMetadata


class GeometryValidationError(ValueError):
    pass
