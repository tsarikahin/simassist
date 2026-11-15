from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from simassist.api.dependencies import (
    JobManagerDep,
    ProjectContextDep,
    get_data_root,
)
from simassist.jobs.models import Job, JobStatus, JobType
from simassist.projects.context import ProjectContext
from simassist.projects.workspace import WorkspaceRepository

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
    overrides = WorkspaceRepository(get_data_root() / "jobs.db").geometry_overrides(project_id)
    items = [
        job
        for job in manager.list_by_project(project_id)
        if job.type == JobType.GEOMETRY_CREATE
        and job.status == JobStatus.COMPLETED
        and job.result is not None
        and job.result.get("artifact_id")
        and not overrides.get(str(job.id), {}).get("deleted", 0)
    ]
    for job in items:
        display_name = overrides.get(str(job.id), {}).get("display_name")
        if display_name:
            job.input["name"] = display_name
    return items


class RenameGeometryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def _geometry_job(project_id: UUID, geometry_job_id: UUID, manager: JobManagerDep):
    try:
        job = manager.repository.get(geometry_job_id)
    except (KeyError, AttributeError):
        matching = [j for j in manager.list_by_project(project_id) if j.id == geometry_job_id]
        if not matching:
            raise HTTPException(status_code=404, detail="Geometry not found")
        job = matching[0]
    if job.project_id != project_id or job.type != JobType.GEOMETRY_CREATE:
        raise HTTPException(status_code=404, detail="Geometry not found")
    return job


@router.patch("/geometries/{geometry_job_id}")
def rename_geometry(project_id: UUID, geometry_job_id: UUID,
                    request: RenameGeometryRequest, manager: JobManagerDep):
    _geometry_job(project_id, geometry_job_id, manager)
    WorkspaceRepository(get_data_root() / "jobs.db").update_geometry(
        project_id, geometry_job_id, name=request.name.strip())
    return {"ok": True}


@router.delete("/geometries/{geometry_job_id}")
def hide_geometry(project_id: UUID, geometry_job_id: UUID,
                  manager: JobManagerDep, context: ProjectContextDep):
    _geometry_job(project_id, geometry_job_id, manager)
    WorkspaceRepository(get_data_root() / "jobs.db").update_geometry(
        project_id, geometry_job_id, deleted=True)
    if context.get(project_id).active_geometry_job_id == geometry_job_id:
        context.clear_active_geometry(project_id)
    return {"ok": True, "note": "Geometry hidden; existing jobs and artifacts preserved"}

