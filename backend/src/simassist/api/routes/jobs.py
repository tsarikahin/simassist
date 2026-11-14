from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from simassist.api.dependencies import JobManagerDep
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshRequest
from simassist.jobs.models import Job, JobType

router = APIRouter(
    prefix="/api",
    tags=["Jobs"],
)


class JobCreateRequest(BaseModel):
    project_id: UUID
    type: JobType
    input: dict = Field(default_factory=dict)


def validate_job_input(
    job_type: JobType,
    payload: dict,
) -> dict:
    """Validate and normalize job inputs before queueing."""

    if job_type == JobType.GEOMETRY_CREATE:
        model = GeometrySpec.model_validate(payload)

    elif job_type == JobType.MESH_GENERATE:
        model = MeshRequest.model_validate(payload)

    else:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported job type: {job_type.value}",
        )

    return model.model_dump(mode="json")


@router.post(
    "/jobs",
    response_model=Job,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_job(
    request: JobCreateRequest,
    manager: JobManagerDep,
):
    try:
        payload = validate_job_input(
            request.type,
            request.input,
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=exc.errors(
                include_context=False,
                include_input=False,
                include_url=False,
            ),
        ) from exc

    return manager.submit(
        project_id=request.project_id,
        job_type=request.type,
        payload=payload,
    )


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(
    job_id: UUID,
    manager: JobManagerDep,
):
    try:
        return manager.get(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        ) from exc


@router.get(
    "/projects/{project_id}/jobs",
    response_model=list[Job],
)
def list_project_jobs(
    project_id: UUID,
    manager: JobManagerDep,
):
    return manager.list_by_project(project_id)
