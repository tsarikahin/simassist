from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from simassist.api.dependencies import ArtifactStoreDep, ProjectContextDep
from simassist.core.models.artifact import ArtifactType
from simassist.projects.cad_faces import CadFaceService
from simassist.simulation.visualization.gmsh_preview import CadFace, GeometryPreview

router = APIRouter(prefix="/api/projects/{project_id}", tags=["CAD faces"])


class CadSelectionRequest(BaseModel):
    geometry_revision_id: UUID
    face_key: str | None = None


class CadSelectionResponse(BaseModel):
    ok: bool
    selection: CadFace | None
    clarification_required: bool


def checked(call):
    try:
        return call()
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(404, "CAD geometry or preview not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/geometries/{revision_id}/faces", response_model=list[CadFace])
def list_faces(
    project_id: UUID,
    revision_id: UUID,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadFaceService(store, context).faces(project_id, revision_id)
    )


@router.get("/geometries/{revision_id}/faces/{face_key}", response_model=CadFace)
def inspect_face(
    project_id: UUID,
    revision_id: UUID,
    face_key: str,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadFaceService(store, context).inspect(
            project_id, revision_id, face_key
        )
    )


@router.get("/cad-selection", response_model=CadSelectionResponse)
def get_selection(
    project_id: UUID, store: ArtifactStoreDep, context: ProjectContextDep
):
    return checked(lambda: CadFaceService(store, context).selection(project_id))


@router.put("/cad-selection", response_model=CadSelectionResponse)
def set_selection(
    project_id: UUID,
    request: CadSelectionRequest,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadFaceService(store, context).select(
            project_id, request.geometry_revision_id, request.face_key
        )
    )


@router.get("/cad-previews/{preview_id}", response_model=GeometryPreview)
def get_preview(
    project_id: UUID,
    preview_id: UUID,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    def load():
        artifact = store.get(preview_id)
        if (
            artifact.project_id != project_id
            or artifact.type != ArtifactType.GEOMETRY_PREVIEW
            or len(artifact.parent_ids) != 1
        ):
            raise KeyError("CAD preview not found")
        return CadFaceService(store, context).preview(
            project_id, artifact.parent_ids[0]
        )

    return checked(load)
