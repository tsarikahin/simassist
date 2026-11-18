from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from simassist.api.dependencies import ArtifactStoreDep, ProjectContextDep
from simassist.core.models.artifact import ArtifactType
from simassist.projects.cad_geometry import CadGeometryService
from simassist.simulation.visualization.gmsh_preview import (
    CadEntity,
    CadFace,
    GeometryPreview,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["CAD geometry"])


class CadSelectionRequest(BaseModel):
    geometry_revision_id: UUID
    face_key: str | None = None


class CadSelectionResponse(BaseModel):
    ok: bool
    selection: CadFace | None
    clarification_required: bool


class EntitySelectionRequest(BaseModel):
    geometry_revision_id: UUID
    dimension: int | None = Field(default=None, ge=0, le=3)
    tag: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def complete_entity(self):
        if (self.dimension is None) != (self.tag is None):
            raise ValueError(
                "Provide both entity dimension and tag, or neither to clear"
            )
        return self


class EntitySelectionResponse(BaseModel):
    ok: bool
    selection: CadEntity | None
    clarification_required: bool


@router.get("/geometries/{revision_id}/entities", response_model=list[CadEntity])
def list_entities(
    project_id: UUID,
    revision_id: UUID,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadGeometryService(store, context).entities(project_id, revision_id)
    )


@router.get("/geometry-selection", response_model=EntitySelectionResponse)
def get_entity_selection(
    project_id: UUID, store: ArtifactStoreDep, context: ProjectContextDep
):
    return checked(lambda: CadGeometryService(store, context).entity_selection(project_id))


@router.put("/geometry-selection", response_model=EntitySelectionResponse)
def set_entity_selection(
    project_id: UUID,
    request: EntitySelectionRequest,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadGeometryService(store, context).select_entity(
            project_id, request.geometry_revision_id, request.dimension, request.tag
        )
    )


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
        lambda: CadGeometryService(store, context).faces(project_id, revision_id)
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
        lambda: CadGeometryService(store, context).inspect(
            project_id, revision_id, face_key
        )
    )


@router.get("/cad-selection", response_model=CadSelectionResponse)
def get_selection(
    project_id: UUID, store: ArtifactStoreDep, context: ProjectContextDep
):
    return checked(lambda: CadGeometryService(store, context).selection(project_id))


@router.put("/cad-selection", response_model=CadSelectionResponse)
def set_selection(
    project_id: UUID,
    request: CadSelectionRequest,
    store: ArtifactStoreDep,
    context: ProjectContextDep,
):
    return checked(
        lambda: CadGeometryService(store, context).select(
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
        return CadGeometryService(store, context).preview(
            project_id, artifact.parent_ids[0]
        )

    return checked(load)
