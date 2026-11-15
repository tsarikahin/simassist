from __future__ import annotations

from enum import IntEnum, StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class MeshDimension(IntEnum):
    TWO_D = 2
    THREE_D = 3


class MeshElementFamily(StrEnum):
    TETRAHEDRAL = "tetrahedral"
    HEXAHEDRAL = "hexahedral"


class MeshSettings(BaseModel):
    dimension: MeshDimension = MeshDimension.THREE_D

    element_family: MeshElementFamily = MeshElementFamily.TETRAHEDRAL

    min_size: float = Field(default=1.0, gt=0)
    max_size: float = Field(default=5.0, gt=0)
    algorithm: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_settings(self):
        if self.min_size > self.max_size:
            raise ValueError("min_size must be less than or equal to max_size")

        if (
            self.dimension == MeshDimension.TWO_D
            and self.element_family == MeshElementFamily.HEXAHEDRAL
        ):
            raise ValueError("Hexahedral elements require a 3D mesh")

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
