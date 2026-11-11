from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class ArtifactType(StrEnum):
    GEOMETRY = "geometry"
    MESH = "mesh"
    SOLVER_INPUT = "solver_input"
    SOLVER_OUTPUT = "solver_output"
    RESULT = "result"
    REPORT = "report"
    OTHER = "other"


class Artifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    type: ArtifactType
    filename: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parent_ids: list[UUID] = Field(default_factory=list)


class ArtifactCreate(BaseModel):
    project_id: UUID
    type: ArtifactType
    source_path: Path
    parent_ids: list[UUID] = Field(default_factory=list)
