from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel

from simassist.jobs.models import JobStatus, JobType
from simassist.jobs.repository import JobRepository


class ProjectContext(BaseModel):
    """Persisted selection for a simulation project."""

    project_id: UUID
    active_geometry_job_id: UUID | None = None
    active_geometry_artifact_id: UUID | None = None
    updated_at: datetime | None = None


class ProjectContextRepository:
    """Store active geometry selections in the existing jobs DB."""

    def __init__(
        self,
        db_path: Path,
        job_repository: JobRepository,
    ) -> None:
        self.db_path = db_path.resolve()
        self.job_repository = job_repository
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS project_context (
                    project_id TEXT PRIMARY KEY,
                    active_geometry_job_id TEXT,
                    active_geometry_artifact_id TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def get(self, project_id: UUID) -> ProjectContext:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT active_geometry_job_id,
                       active_geometry_artifact_id,
                       updated_at
                FROM project_context
                WHERE project_id = ?
                """,
                (str(project_id),),
            ).fetchone()

        if row is None:
            return ProjectContext(project_id=project_id)

        return ProjectContext(
            project_id=project_id,
            active_geometry_job_id=(UUID(row[0]) if row[0] else None),
            active_geometry_artifact_id=(UUID(row[1]) if row[1] else None),
            updated_at=datetime.fromisoformat(row[2]),
        )

    def set_active_geometry(
        self,
        project_id: UUID,
        geometry_job_id: UUID,
    ) -> ProjectContext:
        """Activate an existing completed geometry job."""

        job = self.job_repository.get(geometry_job_id)

        if job.project_id != project_id:
            raise ValueError("Geometry job belongs to a different project")

        if job.type != JobType.GEOMETRY_CREATE:
            raise ValueError("The selected job is not a geometry job")

        if job.status != JobStatus.COMPLETED:
            raise ValueError("Geometry must be completed before selection")

        result = job.result or {}
        artifact_id = result.get("artifact_id")

        if not artifact_id:
            raise ValueError("Completed geometry has no artifact ID")

        geometry_artifact_id = UUID(str(artifact_id))
        updated_at = datetime.now(UTC)

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO project_context (
                    project_id,
                    active_geometry_job_id,
                    active_geometry_artifact_id,
                    updated_at
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id)
                DO UPDATE SET
                    active_geometry_job_id =
                        excluded.active_geometry_job_id,
                    active_geometry_artifact_id =
                        excluded.active_geometry_artifact_id,
                    updated_at =
                        excluded.updated_at
                """,
                (
                    str(project_id),
                    str(geometry_job_id),
                    str(geometry_artifact_id),
                    updated_at.isoformat(),
                ),
            )

        return self.get(project_id)

    def clear_active_geometry(
        self,
        project_id: UUID,
    ) -> ProjectContext:
        """Clear the selected geometry without deleting artifacts."""

        with self._connect() as conn:
            conn.execute(
                """
                DELETE FROM project_context
                WHERE project_id = ?
                """,
                (str(project_id),),
            )

        return self.get(project_id)
