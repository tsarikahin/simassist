from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from simassist.api.dependencies import ArtifactStoreDep, JobManagerDep
from simassist.api.routes.mesh_previews import build_mesh_preview
from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import Job, JobStatus, JobType

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Mesh versions"])


def _geometry_artifact(
    project_id: UUID, geometry_job_id: UUID, manager: JobManagerDep
) -> UUID:
    try:
        job = manager.get(geometry_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Geometry not found") from exc
    if (
        job.project_id != project_id
        or job.type != JobType.GEOMETRY_CREATE
        or job.status != JobStatus.COMPLETED
    ):
        raise HTTPException(status_code=404, detail="Completed geometry not found")
    try:
        return UUID(str((job.result or {})["artifact_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=422, detail="Geometry artifact ID invalid"
        ) from exc


def find_mesh_versions(
    project_id: UUID, geometry_job_id: UUID, manager: JobManagerDep
) -> list[Job]:
    """Find completed meshes by the immutable geometry artifact, newest first."""
    geometry_artifact_id = _geometry_artifact(project_id, geometry_job_id, manager)
    matches = []
    for job in manager.list_by_project(project_id):
        if (
            job.project_id != project_id
            or job.type != JobType.MESH_GENERATE
            or job.status != JobStatus.COMPLETED
            or not (job.result or {}).get("artifact_id")
        ):
            continue
        result = job.result or {}
        request = job.input or {}
        if (
            str(result.get("geometry_artifact_id", "")) == str(geometry_artifact_id)
            or str(request.get("geometry_artifact_id", "")) == str(geometry_artifact_id)
            or str(request.get("geometry_job_id", "")) == str(geometry_job_id)
        ):
            matches.append(job)
    return matches


@router.get("/geometries/{geometry_job_id}/meshes")
def list_geometry_meshes(
    project_id: UUID, geometry_job_id: UUID, manager: JobManagerDep
):
    versions = find_mesh_versions(project_id, geometry_job_id, manager)
    return [
        {
            "job_id": str(job.id),
            "artifact_id": str(job.result["artifact_id"]),
            "created_at": job.created_at.isoformat(),
            "settings": (job.input or {}).get("settings", {}),
            "metadata": (job.result or {}).get("metadata", {}),
        }
        for job in versions
    ]


@router.get("/geometries/{geometry_job_id}/meshes/{mesh_job_id}/preview")
def get_mesh_version_preview(
    project_id: UUID,
    geometry_job_id: UUID,
    mesh_job_id: UUID,
    manager: JobManagerDep,
    store: ArtifactStoreDep,
):
    geometry_artifact_id = _geometry_artifact(project_id, geometry_job_id, manager)
    job = next(
        (
            item
            for item in find_mesh_versions(project_id, geometry_job_id, manager)
            if item.id == mesh_job_id
        ),
        None,
    )
    if job is None:
        raise HTTPException(
            status_code=404, detail="Mesh version not found for geometry"
        )
    try:
        artifact_id = UUID(str(job.result["artifact_id"]))
        artifact = store.get(artifact_id)
        if (
            artifact.project_id != project_id
            or artifact.type != ArtifactType.MESH
            or geometry_artifact_id not in artifact.parent_ids
        ):
            raise HTTPException(
                status_code=404, detail="Mesh artifact does not belong to geometry"
            )
        path = store.resolve_path(artifact_id)
        if path.suffix.lower() != ".msh":
            raise HTTPException(status_code=422, detail="Expected .msh artifact")
        preview = build_mesh_preview(path)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Mesh artifact missing") from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Mesh preview failed: {exc}"
        ) from exc
    return {**preview, "mesh_job_id": str(job.id), "mesh_artifact_id": str(artifact_id)}
