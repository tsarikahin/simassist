from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from simassist.api.dependencies import (
    JobManagerDep,
    ProjectContextDep,
)
from simassist.jobs.models import Job, JobStatus, JobType
from simassist.projects.context import ProjectContext

router = APIRouter(
    prefix="/api/projects/{project_id}",
    tags=["Projects"],
)


class ActiveGeometryRequest(BaseModel):
    geometry_job_id: UUID


@router.get("/context", response_model=ProjectContext)
def get_project_context(
    project_id: UUID,
    context: ProjectContextDep,
):
    return context.get(project_id)


@router.put(
    "/active-geometry",
    response_model=ProjectContext,
)
def set_active_geometry(
    project_id: UUID,
    request: ActiveGeometryRequest,
    context: ProjectContextDep,
):
    try:
        return context.set_active_geometry(
            project_id=project_id,
            geometry_job_id=request.geometry_job_id,
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Geometry job not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc


@router.delete(
    "/active-geometry",
    response_model=ProjectContext,
)
def clear_active_geometry(
    project_id: UUID,
    context: ProjectContextDep,
):
    return context.clear_active_geometry(project_id)


@router.get(
    "/geometries",
    response_model=list[Job],
)
def list_project_geometries(
    project_id: UUID,
    manager: JobManagerDep,
):
    return [
        job
        for job in manager.list_by_project(project_id)
        if job.type == JobType.GEOMETRY_CREATE
        and job.status == JobStatus.COMPLETED
        and job.result is not None
        and job.result.get("artifact_id")
    ]
