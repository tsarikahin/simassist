"""Authoritative CAD inspection and selection; no native Gmsh calls in HTTP threads."""

import logging
import subprocess
import sys
from uuid import UUID, uuid5

from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import JobStatus, JobType
from simassist.projects.context import ProjectContextRepository
from simassist.projects.workspace import WorkspaceRepository
from simassist.simulation.visualization.gmsh_preview import GeometryPreview, entity_key
from simassist.storage.local import LocalArtifactStore

logger = logging.getLogger(__name__)


class CadGeometryService:
    def __init__(self, store: LocalArtifactStore, context: ProjectContextRepository):
        self.store = store
        self.context = context

    def active_geometry(self, project_id: UUID, revision_id: UUID):
        artifact = self.store.get(revision_id)
        if artifact.project_id != project_id or artifact.type != ArtifactType.GEOMETRY:
            raise KeyError("Geometry not found")
        context = self.context.get(project_id)
        if (
            context.active_geometry_artifact_id != revision_id
            or not context.active_geometry_job_id
        ):
            raise ValueError(
                "Geometry revision is stale; select the active geometry again"
            )
        job = self.context.job_repository.get(context.active_geometry_job_id)
        if (
            job.project_id != project_id
            or job.type != JobType.GEOMETRY_CREATE
            or job.status != JobStatus.COMPLETED
            or str((job.result or {}).get("artifact_id")) != str(revision_id)
            or WorkspaceRepository(self.context.db_path)
            .geometry_overrides(project_id)
            .get(str(job.id), {})
            .get("deleted", 0)
        ):
            raise ValueError("Active geometry is unavailable")
        return job

    def preview(self, project_id: UUID, revision_id: UUID) -> GeometryPreview:
        job = self.active_geometry(project_id, revision_id)
        candidates = [
            item
            for item in self.store.list_by_project(project_id)
            if item.type == ArtifactType.GEOMETRY_PREVIEW
            and item.parent_ids == [revision_id]
        ]
        for item in reversed(candidates):
            preview = GeometryPreview.model_validate_json(
                self.store.resolve_path(item.id).read_text(encoding="utf-8")
            )
            if (
                preview.geometry_revision_id == revision_id
                and preview.topology_version == 1
            ):
                self._validate_preview(preview, revision_id)
                return preview
        # Older immutable previews remain untouched. Generate a new derived artifact
        # in an isolated process (Gmsh has global state and requires its main thread).
        logger.info(
            "Upgrading CAD preview project=%s revision=%s", project_id, revision_id
        )
        try:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "simassist.projects.cad_geometry",
                    str(self.store.root),
                    str(project_id),
                    str(revision_id),
                    str(job.input.get("units", "unknown")),
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            logger.exception("CAD preview upgrade failed revision=%s", revision_id)
            raise ValueError("CAD topology preview could not be generated") from exc
        # Read the newly derived artifact, without repeating generation on failure.
        for item in reversed(self.store.list_by_project(project_id)):
            if item.type == ArtifactType.GEOMETRY_PREVIEW and item.parent_ids == [
                revision_id
            ]:
                preview = GeometryPreview.model_validate_json(
                    self.store.resolve_path(item.id).read_text(encoding="utf-8")
                )
                if (
                    preview.geometry_revision_id == revision_id
                    and preview.topology_version == 1
                ):
                    self._validate_preview(preview, revision_id)
                    return preview
        raise ValueError("CAD topology preview is unavailable")

    @staticmethod
    def _validate_preview(preview: GeometryPreview, revision: UUID):
        if (
            len(preview.triangle_face_keys) != len(preview.triangles)
            or any(face.geometry_revision_id != revision for face in preview.faces)
            or not set(preview.triangle_face_keys)
            <= {face.face_key for face in preview.faces}
        ):
            raise ValueError("Invalid CAD face provenance")
        entities = {item.entity_key: item for item in preview.entities}
        if (
            not entities
            or len(entities) != len(preview.entities)
            or any(
                item.geometry_revision_id != revision
                or item.entity_key != entity_key(revision, item.dimension, item.tag)
                or item.entity_id != uuid5(revision, f"{item.dimension}:{item.tag}")
                or any(
                    key not in entities
                    or entities[key].dimension != 3
                    or item.entity_key not in entities[key].boundary_entity_keys
                    for key in item.owner_body_keys
                )
                or any(
                    key not in entities or entities[key].dimension != item.dimension - 1
                    for key in item.boundary_entity_keys
                )
                for item in preview.entities
            )
        ):
            raise ValueError("Invalid CAD entity provenance")
        for keys, cells, dimension in (
            (preview.triangle_face_keys, preview.triangles, 2),
            (preview.edge_entity_keys, preview.edge_segments, 1),
            (
                preview.vertex_entity_keys,
                [(i,) for i in preview.vertex_point_indices],
                0,
            ),
        ):
            if len(keys) != len(cells) or any(
                key not in entities
                or entities[key].dimension != dimension
                or any(index < 0 or index >= len(preview.points) for index in cell)
                for key, cell in zip(keys, cells, strict=True)
            ):
                raise ValueError("Invalid CAD picking provenance")

    def entities(self, project_id: UUID, revision_id: UUID):
        return self.preview(project_id, revision_id).entities

    def inspect_entity(
        self, project_id: UUID, revision_id: UUID, dimension: int, tag: int
    ):
        for entity in self.entities(project_id, revision_id):
            if entity.dimension == dimension and entity.tag == tag:
                return entity
        raise ValueError("Entity does not belong to this geometry revision")

    def select_entity(
        self,
        project_id: UUID,
        revision_id: UUID,
        dimension: int | None,
        tag: int | None,
    ):
        self.active_geometry(project_id, revision_id)
        entity = (
            self.inspect_entity(project_id, revision_id, dimension, tag)
            if tag is not None
            else None
        )
        self.context.set_entity_selection(project_id, revision_id, dimension, tag)
        return {
            "ok": True,
            "selection": entity,
            "clarification_required": entity is None,
        }

    def entity_selection(self, project_id: UUID):
        context = self.context.get(project_id)
        if (
            context.selected_cad_revision_id is None
            or context.selected_cad_dimension is None
            or context.selected_cad_tag is None
        ):
            return {"ok": True, "selection": None, "clarification_required": True}
        entity = self.inspect_entity(
            project_id,
            context.selected_cad_revision_id,
            context.selected_cad_dimension,
            context.selected_cad_tag,
        )
        current = self.context.get(project_id)
        if (
            current.active_geometry_artifact_id,
            current.selected_cad_dimension,
            current.selected_cad_tag,
        ) != (context.selected_cad_revision_id, entity.dimension, entity.tag):
            raise ValueError(
                "Geometry selection changed during inspection; retrieve it again"
            )
        return {"ok": True, "selection": entity, "clarification_required": False}

    def faces(self, project_id: UUID, revision_id: UUID):
        return self.preview(project_id, revision_id).faces

    def inspect(self, project_id: UUID, revision_id: UUID, face_key: str):
        for face in self.faces(project_id, revision_id):
            if face.face_key == face_key:
                return face
        raise ValueError("Face does not belong to this geometry revision")

    def select(self, project_id: UUID, revision_id: UUID, face_key: str | None):
        self.active_geometry(project_id, revision_id)
        face = self.inspect(project_id, revision_id, face_key) if face_key else None
        self.context.set_cad_selection(project_id, revision_id, face_key)
        return {"ok": True, "selection": face, "clarification_required": face is None}

    def selection(self, project_id: UUID):
        context = self.context.get(project_id)
        if not context.selected_cad_face_key or not context.selected_cad_revision_id:
            return {"ok": True, "selection": None, "clarification_required": True}
        face = self.inspect(
            project_id, context.selected_cad_revision_id, context.selected_cad_face_key
        )
        return {"ok": True, "selection": face, "clarification_required": False}


if __name__ == "__main__":
    from pathlib import Path

    from simassist.simulation.visualization.gmsh_preview import GmshPreviewService

    artifact_store = LocalArtifactStore(Path(sys.argv[1]))
    GmshPreviewService(
        artifact_store.root / "cad-preview-work", artifact_store, UUID(sys.argv[2])
    ).generate(UUID(sys.argv[3]), coordinate_units=sys.argv[4])
