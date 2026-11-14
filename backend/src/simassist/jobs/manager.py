from __future__ import annotations

from typing import Any
from uuid import UUID

from simassist.jobs.models import Job, JobType
from simassist.jobs.repository import JobRepository


class JobManager:
    """Application service for submitting and querying jobs."""

    def __init__(self, repository: JobRepository):
        self.repository = repository

    def submit(
        self,
        project_id: UUID,
        job_type: JobType,
        payload: dict[str, Any],
    ) -> Job:
        job = Job(
            project_id=project_id,
            type=job_type,
            input=payload,
        )
        return self.repository.submit(job)

    def get(self, job_id: UUID) -> Job:
        return self.repository.get(job_id)

    def list_by_project(self, project_id: UUID) -> list[Job]:
        return self.repository.list_by_project(project_id)
