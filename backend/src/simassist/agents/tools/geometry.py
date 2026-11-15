from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import ValidationError

from simassist.core.models.geometry import GeometrySpec
from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobType


class GeometryTools:
    """Agent-facing geometry operations.

    LLM providers do not depend on the execution backend.
    """

    def __init__(
        self,
        job_manager: JobManager,
        project_id: UUID,
    ) -> None:
        self.job_manager = job_manager
        self.project_id = project_id

    def create_geometry(
        self,
        specification: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate a geometry specification and submit a job."""

        try:
            geometry = GeometrySpec.model_validate(specification)
        except ValidationError as exc:
            return {
                "ok": False,
                "error": "Invalid geometry specification",
                "details": exc.errors(
                    include_context=False,
                    include_input=False,
                    include_url=False,
                ),
            }

        job = self.job_manager.submit(
            project_id=self.project_id,
            job_type=JobType.GEOMETRY_CREATE,
            payload=geometry.model_dump(mode="json"),
        )

        return {
            "ok": True,
            "job_id": str(job.id),
            "status": job.status.value,
            "job_type": job.type.value,
            "message": "Geometry creation job submitted",
        }

    def get_job_status(
        self,
        job_id: str,
    ) -> dict[str, Any]:
        """Inspect a previously submitted job."""

        try:
            job = self.job_manager.get(UUID(job_id))
        except (ValueError, KeyError):
            return {
                "ok": False,
                "error": "Job not found",
            }

        if job.project_id != self.project_id:
            return {
                "ok": False,
                "error": "Job not found",
            }

        return {
            "ok": True,
            "job_id": str(job.id),
            "status": job.status.value,
            "job_type": job.type.value,
            "result": job.result,
            "error": job.error,
        }
