"""Authoritative CAD inspection and selection; no native Gmsh calls in HTTP threads."""

import logging
import subprocess
import sys
from uuid import UUID

from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import JobStatus, JobType
from simassist.projects.context import ProjectContextRepository
from simassist.projects.workspace import WorkspaceRepository
from simassist.simulation.visualization.gmsh_preview import GeometryPreview
from simassist.storage.local import LocalArtifactStore

logger = logging.getLogger(__name__)


class CadFaceService:
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
            if preview.geometry_revision_id == revision_id:
                if (
                    len(preview.triangle_face_keys) != len(preview.triangles)
                    or any(
                        face.geometry_revision_id != revision_id
                        for face in preview.faces
                    )
                    or not set(preview.triangle_face_keys)
                    <= {face.face_key for face in preview.faces}
                ):
                    raise ValueError("Invalid CAD face provenance")
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
                    "simassist.projects.cad_faces",
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
                if preview.geometry_revision_id == revision_id:
                    return preview
        raise ValueError("CAD topology preview is unavailable")

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
