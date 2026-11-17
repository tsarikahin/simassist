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
    selected_mesh_job_id: UUID | None = None
    selected_cad_revision_id: UUID | None = None
    selected_cad_face_key: str | None = None
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

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(project_context)")
            }
            if "selected_mesh_job_id" not in columns:
                conn.execute(
                    "ALTER TABLE project_context ADD COLUMN selected_mesh_job_id TEXT"
                )
            for name in ("selected_cad_revision_id", "selected_cad_face_key"):
                if name not in columns:
                    conn.execute(f"ALTER TABLE project_context ADD COLUMN {name} TEXT")

    def get(self, project_id: UUID) -> ProjectContext:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT active_geometry_job_id,
                       active_geometry_artifact_id,
                       updated_at, selected_mesh_job_id,
                       selected_cad_revision_id, selected_cad_face_key
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
            selected_mesh_job_id=UUID(row[3]) if row[3] else None,
            selected_cad_revision_id=UUID(row[4]) if row[4] else None,
            selected_cad_face_key=row[5],
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
                    selected_mesh_job_id = CASE
                        WHEN project_context.active_geometry_job_id=excluded.active_geometry_job_id
                        THEN project_context.selected_mesh_job_id ELSE NULL END,
                    selected_cad_revision_id = CASE
                        WHEN project_context.active_geometry_artifact_id=excluded.active_geometry_artifact_id
                        THEN project_context.selected_cad_revision_id ELSE NULL END,
                    selected_cad_face_key = CASE
                        WHEN project_context.active_geometry_artifact_id=excluded.active_geometry_artifact_id
                        THEN project_context.selected_cad_face_key ELSE NULL END,
                    updated_at = excluded.updated_at
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

    def set_selected_mesh(
        self, project_id: UUID, geometry_job_id: UUID, mesh_job_id: UUID
    ):
        """Select only a completed version of the active geometry, without changing jobs."""
        mesh = self.job_repository.get(mesh_job_id)
        if (
            mesh.project_id != project_id
            or mesh.type != JobType.MESH_GENERATE
            or mesh.status != JobStatus.COMPLETED
        ):
            raise ValueError("Selected mesh must be a completed mesh in this project")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT active_geometry_job_id,active_geometry_artifact_id FROM project_context WHERE project_id=?",
                (str(project_id),),
            ).fetchone()
            if not row or row[0] != str(geometry_job_id):
                raise ValueError(
                    "Active geometry changed; select the geometry before its mesh"
                )
            if str((mesh.result or {}).get("geometry_artifact_id", "")) != row[1]:
                raise ValueError("Selected mesh belongs to another geometry revision")
            conn.execute(
                "UPDATE project_context SET selected_mesh_job_id=?,updated_at=? WHERE project_id=?",
                (str(mesh_job_id), datetime.now(UTC).isoformat(), str(project_id)),
            )
        return self.get(project_id)

    def set_cad_selection(
        self, project_id: UUID, revision_id: UUID, face_key: str | None
    ) -> ProjectContext:
        """Compare-and-set after topology validation; geometry changes cannot race a click."""
        with self._connect() as conn:
            changed = conn.execute(
                """UPDATE project_context SET selected_cad_revision_id=?,
                   selected_cad_face_key=?, updated_at=?
                   WHERE project_id=? AND active_geometry_artifact_id=?""",
                (
                    str(revision_id) if face_key else None,
                    face_key,
                    datetime.now(UTC).isoformat(),
                    str(project_id),
                    str(revision_id),
                ),
            ).rowcount
            if not changed:
                raise ValueError(
                    "Geometry revision is stale; select the active geometry again"
                )
        return self.get(project_id)
