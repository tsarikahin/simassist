"""Read-only quality diagnostics for verified, project-scoped mesh versions."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from simassist.api.dependencies import ArtifactStoreDep, JobManagerDep
from simassist.api.routes.mesh_versions import _geometry_artifact, find_mesh_versions
from simassist.core.models.artifact import ArtifactType
from simassist.simulation.meshing.quality import analyze_mesh_file

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Mesh quality"])


@router.get("/geometries/{geometry_job_id}/meshes/{mesh_job_id}/quality")
def get_mesh_quality(
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
        artifact_id = UUID(str((job.result or {})["artifact_id"]))
        artifact = store.get(artifact_id)
        if (
            artifact.project_id != project_id
            or artifact.type != ArtifactType.MESH
            or geometry_artifact_id not in artifact.parent_ids
        ):
            raise HTTPException(
                status_code=404, detail="Mesh does not belong to geometry"
            )
        mesh_path = store.resolve_path(artifact_id)
        if mesh_path.suffix.lower() != ".msh":
            raise HTTPException(status_code=422, detail="Expected .msh artifact")
        quality = analyze_mesh_file(mesh_path)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Mesh artifact missing") from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Quality analysis failed: {exc}"
        ) from exc

    return {**quality, "mesh_job_id": str(job.id), "mesh_artifact_id": str(artifact_id)}
