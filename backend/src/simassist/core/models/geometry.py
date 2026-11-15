from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


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
    CSG = "csg"


class PrimitiveType(StrEnum):
    BOX = "box"
    CYLINDER = "cylinder"
    SPHERE = "sphere"
    LINE = "line"
    RECTANGLE = "rectangle"
    SQUARE = "square"
    DISK = "disk"


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


class InlineCSGOperation(StrEnum):
    CUT = "cut"
    FUSE = "fuse"
    INTERSECT = "intersect"


class InlineCSGGeometry(BaseModel):
    """Build a boolean CAD shape from inline primitive definitions.

    Cut subtracts all subsequent operands from the first primitive.
    This model does not mutate existing STEP artifacts.
    """

    source: Literal["csg"] = "csg"
    operation: InlineCSGOperation
    operands: list[PrimitiveGeometry] = Field(min_length=2)

    @model_validator(mode="after")
    def validate_operand_dimensions(self):
        dims = {
            PrimitiveType.LINE: 1,
            PrimitiveType.SQUARE: 2,
            PrimitiveType.RECTANGLE: 2,
            PrimitiveType.DISK: 2,
            PrimitiveType.BOX: 3,
            PrimitiveType.CYLINDER: 3,
            PrimitiveType.SPHERE: 3,
        }
        dimensions = {dims[operand.primitive] for operand in self.operands}
        if len(dimensions) != 1 or dimensions == {1}:
            raise ValueError(
                "Boolean CSG requires operands of the same dimension (2D or 3D)"
            )
        return self


GeometryDefinition = Annotated[
    PrimitiveGeometry | CADImportGeometry | BooleanGeometry | InlineCSGGeometry,
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
    dimension: int = Field(default=3, ge=1, le=3)
    curve_count: int = Field(default=0, ge=0)
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
