from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from simassist.api.dependencies import ArtifactStoreDep, JobManagerDep
from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import JobStatus, JobType
from simassist.simulation.visualization.mesh_preview import (  # noqa: F401 - compatibility imports
    build_mesh_preview,
    build_tetra_surface_preview,
)
from simassist.simulation.visualization.preview_cache import cached_mesh_preview

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Mesh previews"])


@router.get("/geometries/{geometry_job_id}/mesh-preview")
def get_latest_mesh_preview(
    project_id: UUID,
    geometry_job_id: UUID,
    manager: JobManagerDep,
    store: ArtifactStoreDep,
):
    try:
        geometry = manager.get(geometry_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Geometry not found") from exc

    if (
        geometry.project_id != project_id
        or geometry.type != JobType.GEOMETRY_CREATE
        or geometry.status != JobStatus.COMPLETED
    ):
        raise HTTPException(status_code=404, detail="Completed geometry not found")

    geometry_artifact_id = str((geometry.result or {}).get("artifact_id", ""))
    if not geometry_artifact_id:
        raise HTTPException(status_code=404, detail="Geometry has no STEP artifact")

    # list_by_project is newest-first. Match by saved geometry artifact,
    # not by mesh title or the currently selected frontend view.
    match = None
    for job in manager.list_by_project(project_id):
        if job.type != JobType.MESH_GENERATE or job.status != JobStatus.COMPLETED:
            continue
        result = job.result or {}
        payload = job.input or {}
        if (
            str(result.get("geometry_artifact_id", "")) == geometry_artifact_id
            or str(payload.get("geometry_artifact_id", "")) == geometry_artifact_id
            or str(payload.get("geometry_job_id", "")) == str(geometry_job_id)
        ):
            match = job
            break

    if match is None:
        raise HTTPException(
            status_code=404, detail="No completed mesh exists for this geometry"
        )

    mesh_id = (match.result or {}).get("artifact_id")
    if not mesh_id:
        raise HTTPException(status_code=404, detail="Mesh job has no artifact")
    try:
        artifact_id = UUID(str(mesh_id))
        artifact = store.get(artifact_id)
        if (
            artifact.project_id != project_id
            or artifact.type != ArtifactType.MESH
            or UUID(geometry_artifact_id) not in artifact.parent_ids
        ):
            raise HTTPException(
                status_code=404, detail="Mesh artifact not found for geometry"
            )
        path = store.resolve_path(artifact_id)
        if path.suffix.lower() != ".msh":
            raise HTTPException(status_code=422, detail="Expected Gmsh .msh artifact")
        preview = cached_mesh_preview(path, artifact_id)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=404, detail="Mesh artifact file missing"
        ) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Mesh preview failed: {exc}"
        ) from exc

    return preview.response(match.id, artifact_id)
