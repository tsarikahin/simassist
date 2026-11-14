from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from simassist.jobs.models import Job, JobStatus


class JobRepository:
    """Persistent SQLite job queue."""

    def __init__(self, db_path: Path):
        self.db_path = db_path.resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=30)

    def _initialize_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_queue
                ON jobs(status, created_at)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_jobs_project
                ON jobs(project_id)
            """)

    def submit(self, job: Job) -> Job:
        """Persist a new queued job."""
        if job.status != JobStatus.QUEUED:
            raise ValueError("New jobs must be queued")

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO jobs (
                    id, project_id, status, created_at, payload
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(job.id),
                    str(job.project_id),
                    job.status.value,
                    job.created_at.isoformat(),
                    job.model_dump_json(),
                ),
            )

        return job

    def get(self, job_id: UUID) -> Job:
        """Retrieve a job by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM jobs WHERE id = ?",
                (str(job_id),),
            ).fetchone()

        if row is None:
            raise KeyError(f"Job not found: {job_id}")

        return Job.model_validate_json(row[0])

    def list_by_project(self, project_id: UUID) -> list[Job]:
        """List jobs for a project."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload FROM jobs
                WHERE project_id = ?
                ORDER BY created_at DESC, rowid DESC
                """,
                (str(project_id),),
            ).fetchall()

        return [Job.model_validate_json(row[0]) for row in rows]

    def claim_next(self) -> Job | None:
        """Atomically claim the oldest queued job."""

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                """
                SELECT payload
                FROM jobs
                WHERE status = ?
                ORDER BY created_at, rowid
                LIMIT 1
                """,
                (JobStatus.QUEUED.value,),
            ).fetchone()

            if row is None:
                return None

            job = Job.model_validate_json(row[0])

            updated = job.model_copy(
                update={
                    "status": JobStatus.RUNNING,
                    "started_at": datetime.now(UTC),
                }
            )

            conn.execute(
                """
                UPDATE jobs
                SET status = ?, payload = ?
                WHERE id = ? AND status = ?
                """,
                (
                    updated.status.value,
                    updated.model_dump_json(),
                    str(job.id),
                    JobStatus.QUEUED.value,
                ),
            )

        return updated

    def complete(self, job_id: UUID, result: dict) -> Job:
        """Mark a running job as completed."""
        return self._finish(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result=result,
        )

    def fail(self, job_id: UUID, error: str) -> Job:
        """Mark a running job as failed."""
        return self._finish(
            job_id=job_id,
            status=JobStatus.FAILED,
            error=error,
        )

    def _finish(
        self,
        job_id: UUID,
        status: JobStatus,
        result: dict | None = None,
        error: str | None = None,
    ) -> Job:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            row = conn.execute(
                "SELECT payload FROM jobs WHERE id = ?",
                (str(job_id),),
            ).fetchone()

            if row is None:
                raise KeyError(f"Job not found: {job_id}")

            job = Job.model_validate_json(row[0])

            if job.status != JobStatus.RUNNING:
                raise ValueError(f"Cannot finish job in status {job.status}")

            updated = job.model_copy(
                update={
                    "status": status,
                    "finished_at": datetime.now(UTC),
                    "result": result,
                    "error": error,
                }
            )

            conn.execute(
                """
                UPDATE jobs
                SET status = ?, payload = ?
                WHERE id = ?
                """,
                (
                    updated.status.value,
                    updated.model_dump_json(),
                    str(job_id),
                ),
            )

        return updated
