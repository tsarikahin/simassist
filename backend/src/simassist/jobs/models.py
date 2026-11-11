
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class JobType(StrEnum):
    GEOMETRY_CREATE = "geometry.create"
    MESH_GENERATE = "mesh.generate"
    SIMULATION_RUN = "simulation.run"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    project_id: UUID
    type: JobType
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC)
    )
    started_at: datetime | None = None
    finished_at: datetime | None = None
    input: dict = Field(default_factory=dict)
    result: dict | None = None
    error: str | None = None
