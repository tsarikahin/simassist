from __future__ import annotations

from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MeshDimension(IntEnum):
    ONE_D = 1
    TWO_D = 2
    THREE_D = 3


class MeshElementFamily(StrEnum):
    LINE = "line"
    TRIANGULAR = "triangular"
    QUADRILATERAL = "quadrilateral"
    TETRAHEDRAL = "tetrahedral"
    HEXAHEDRAL = "hexahedral"


class MeshSettings(BaseModel):
    dimension: MeshDimension = MeshDimension.THREE_D

    element_family: MeshElementFamily | None = None

    min_size: float = Field(default=1.0, gt=0)
    max_size: float = Field(default=5.0, gt=0)
    algorithm: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_settings(self):
        if self.min_size > self.max_size:
            raise ValueError("min_size must be less than or equal to max_size")

        defaults = {
            MeshDimension.ONE_D: MeshElementFamily.LINE,
            MeshDimension.TWO_D: MeshElementFamily.TRIANGULAR,
            MeshDimension.THREE_D: MeshElementFamily.TETRAHEDRAL,
        }
        supported = {
            MeshDimension.ONE_D: {MeshElementFamily.LINE},
            MeshDimension.TWO_D: {
                MeshElementFamily.TRIANGULAR,
                MeshElementFamily.QUADRILATERAL,
            },
            MeshDimension.THREE_D: {
                MeshElementFamily.TETRAHEDRAL,
                MeshElementFamily.HEXAHEDRAL,
            },
        }
        if self.element_family is None:
            self.element_family = defaults[self.dimension]
        if self.element_family not in supported[self.dimension]:
            raise ValueError(
                f"{self.element_family} is not a valid {int(self.dimension)}D element family"
            )
        return self


class MeshRequest(BaseModel):
    geometry_artifact_id: UUID
    settings: MeshSettings = Field(default_factory=MeshSettings)


class MeshMetadata(BaseModel):
    node_count: int = Field(ge=0)
    element_count: int = Field(ge=0)

    element_types: dict[str, int] = Field(default_factory=dict)

    volume_element_types: dict[str, int] = Field(default_factory=dict)


class MeshResult(BaseModel):
    engine: str
    artifact_id: UUID
    geometry_artifact_id: UUID
    metadata: MeshMetadata
