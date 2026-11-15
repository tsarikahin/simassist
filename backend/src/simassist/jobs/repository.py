from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from simassist.jobs.models import Job, JobStatus

FAILED_DEPENDENCIES = {
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


class JobRepository:
    """Persistent SQLite queue with dependency-aware scheduling."""

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
        if job.status != JobStatus.QUEUED:
            raise ValueError("New jobs must be queued")

        with self._connect() as conn:
            self._insert(conn, job)

        return job

    def submit_many(self, jobs: list[Job]) -> list[Job]:
        """Submit related jobs in a single transaction."""
        if not jobs:
            return []

        if any(job.status != JobStatus.QUEUED for job in jobs):
            raise ValueError("New jobs must be queued")

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            for job in jobs:
                self._insert(conn, job)

        return jobs

    @staticmethod
    def _insert(conn: sqlite3.Connection, job: Job) -> None:
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

    def get(self, job_id: UUID) -> Job:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM jobs WHERE id = ?",
                (str(job_id),),
            ).fetchone()

        if row is None:
            raise KeyError(f"Job not found: {job_id}")

        return Job.model_validate_json(row[0])

    def list_by_project(self, project_id: UUID) -> list[Job]:
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
        """Atomically claim the oldest runnable queued job.

        Queued jobs with unfinished dependencies are skipped.
        Failed or missing dependencies propagate failure.
        """

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")

            rows = conn.execute(
                """
                SELECT payload FROM jobs
                WHERE status = ?
                ORDER BY created_at, rowid
                """,
                (JobStatus.QUEUED.value,),
            ).fetchall()

            for row in rows:
                job = Job.model_validate_json(row[0])

                if job.depends_on is not None:
                    dependency_row = conn.execute(
                        "SELECT payload FROM jobs WHERE id = ?",
                        (str(job.depends_on),),
                    ).fetchone()

                    dependency = (
                        Job.model_validate_json(dependency_row[0])
                        if dependency_row
                        else None
                    )

                    failure_reason = None

                    if dependency is None:
                        failure_reason = f"Dependency not found: {job.depends_on}"
                    elif dependency.project_id != job.project_id:
                        failure_reason = "Dependency belongs to another project"
                    elif dependency.status in FAILED_DEPENDENCIES:
                        failure_reason = (
                            f"Dependency {dependency.id} "
                            f"ended with status {dependency.status}"
                        )

                    if failure_reason:
                        failed = job.model_copy(
                            update={
                                "status": JobStatus.FAILED,
                                "finished_at": datetime.now(UTC),
                                "error": failure_reason,
                            }
                        )
                        self._update(conn, failed)
                        continue

                    if dependency.status != JobStatus.COMPLETED:
                        continue

                updated = job.model_copy(
                    update={
                        "status": JobStatus.RUNNING,
                        "started_at": datetime.now(UTC),
                    }
                )

                self._update(conn, updated)
                return updated

        return None

    @staticmethod
    def _update(conn: sqlite3.Connection, job: Job) -> None:
        conn.execute(
            """
            UPDATE jobs
            SET status = ?, payload = ?
            WHERE id = ?
            """,
            (
                job.status.value,
                job.model_dump_json(),
                str(job.id),
            ),
        )

    def complete(self, job_id: UUID, result: dict) -> Job:
        return self._finish(
            job_id=job_id,
            status=JobStatus.COMPLETED,
            result=result,
        )

    def fail(self, job_id: UUID, error: str) -> Job:
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

            self._update(conn, updated)

        return updated
