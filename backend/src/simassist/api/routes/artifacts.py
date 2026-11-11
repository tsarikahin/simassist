from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from simassist.api.dependencies import ArtifactStoreDep
from simassist.core.models.artifact import Artifact

router = APIRouter(
    prefix="/api/projects/{project_id}/artifacts",
    tags=["Artifacts"],
)


@router.get("", response_model=list[Artifact])
def list_artifacts(
    project_id: UUID,
    store: ArtifactStoreDep,
):
    return store.list_by_project(project_id)


@router.get("/{artifact_id}", response_model=Artifact)
def get_artifact(
    project_id: UUID,
    artifact_id: UUID,
    store: ArtifactStoreDep,
):
    try:
        artifact = store.get(artifact_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
        ) from exc

    if artifact.project_id != project_id:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found",
        )

    return artifact


@router.get("/{artifact_id}/download")
def download_artifact(
    project_id: UUID,
    artifact_id: UUID,
    store: ArtifactStoreDep,
):
    try:
        artifact = store.get(artifact_id)

        if artifact.project_id != project_id:
            raise HTTPException(
                status_code=404,
                detail="Artifact not found",
            )

        path = store.resolve_path(artifact_id)

    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=404,
            detail="Artifact file not found",
        ) from exc

    return FileResponse(
        path=path,
        media_type="application/octet-stream",
        filename=artifact.filename,
    )
