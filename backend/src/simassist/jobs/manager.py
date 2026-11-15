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

    def submit_geometry_mesh(
        self,
        project_id: UUID,
        geometry_payload: dict[str, Any],
        mesh_settings: dict[str, Any],
    ) -> tuple[Job, Job]:
        """Submit an atomic geometry -> mesh workflow."""

        geometry_job = Job(
            project_id=project_id,
            type=JobType.GEOMETRY_CREATE,
            input=geometry_payload,
        )

        mesh_job = Job(
            project_id=project_id,
            type=JobType.MESH_GENERATE,
            depends_on=geometry_job.id,
            input={
                "geometry_job_id": str(geometry_job.id),
                "settings": mesh_settings,
            },
        )

        self.repository.submit_many(
            [
                geometry_job,
                mesh_job,
            ]
        )

        return geometry_job, mesh_job

    def get(self, job_id: UUID) -> Job:
        return self.repository.get(job_id)

    def list_by_project(self, project_id: UUID) -> list[Job]:
        return self.repository.list_by_project(project_id)
