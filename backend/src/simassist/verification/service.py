from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from simassist.core.models.artifact import ArtifactType
from simassist.core.models.geometry import GeometryResult
from simassist.core.models.mesh import (
    MeshDimension,
    MeshElementFamily,
    MeshRequest,
    MeshResult,
)
from simassist.jobs.models import Job, JobType
from simassist.storage.base import ArtifactStore


class VerificationError(ValueError):
    """A generated simulation result failed verification."""


class VerificationService:
    """Verify generated artifacts before completing jobs.

    Performs technical integrity checks, not physical validation
    or mesh convergence assessment.
    """

    def __init__(self, artifact_store: ArtifactStore):
        self.artifact_store = artifact_store

    def verify(
        self,
        job: Job,
        result: dict[str, Any],
    ) -> None:
        if job.type == JobType.GEOMETRY_CREATE:
            self._verify_geometry(job, result)

        elif job.type == JobType.MESH_GENERATE:
            self._verify_mesh(job, result)

        else:
            raise VerificationError(f"No verifier registered for {job.type}")

    def _check_artifact(
        self,
        artifact_id: UUID,
        project_id: UUID,
        expected_type: ArtifactType,
        expected_suffix: str,
        parent_id: UUID | None = None,
    ) -> Path:
        try:
            artifact = self.artifact_store.get(artifact_id)
            path = self.artifact_store.resolve_path(artifact_id)
        except (KeyError, FileNotFoundError) as exc:
            raise VerificationError(f"Artifact not found: {artifact_id}") from exc

        if artifact.project_id != project_id:
            raise VerificationError("Artifact belongs to a different project")

        if artifact.type != expected_type:
            raise VerificationError(f"Unexpected artifact type: {artifact.type}")

        if parent_id is not None and parent_id not in artifact.parent_ids:
            raise VerificationError("Artifact parent relationship is invalid")

        if path.suffix.lower() != expected_suffix:
            raise VerificationError(f"Unexpected artifact format: {path.suffix}")

        if not path.is_file() or path.stat().st_size == 0:
            raise VerificationError(f"Artifact file is empty or missing: {artifact_id}")

        return path

    def _verify_geometry(
        self,
        job: Job,
        result: dict[str, Any],
    ) -> None:
        try:
            geometry = GeometryResult.model_validate(result)
            preview_id = UUID(str(result["preview_artifact_id"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise VerificationError("Invalid geometry result") from exc

        dimension = geometry.metadata.dimension
        if dimension == 3 and geometry.metadata.volume_count < 1:
            raise VerificationError("Geometry contains no solid volumes")
        if dimension == 2 and geometry.metadata.surface_count < 1:
            raise VerificationError("Geometry contains no surfaces")
        if dimension == 1 and geometry.metadata.curve_count < 1:
            raise VerificationError("Geometry contains no curves")

        self._check_artifact(
            artifact_id=geometry.artifact_id,
            project_id=job.project_id,
            expected_type=ArtifactType.GEOMETRY,
            expected_suffix=".step",
        )

        preview_path = self._check_artifact(
            artifact_id=preview_id,
            project_id=job.project_id,
            expected_type=ArtifactType.GEOMETRY_PREVIEW,
            expected_suffix=".json",
            parent_id=geometry.artifact_id,
        )

        try:
            preview = json.loads(preview_path.read_text(encoding="utf-8"))

            points = preview["points"]
            triangles = preview["triangles"]
            lines = preview.get("lines", [])

            if not isinstance(points, list) or not points:
                raise VerificationError("Geometry preview contains no points")

            if not isinstance(triangles, list) or not isinstance(lines, list):
                raise VerificationError("Invalid geometry preview cells")
            if dimension == 1 and not lines:
                raise VerificationError("Geometry preview contains no lines")
            if dimension >= 2 and not triangles:
                raise VerificationError("Geometry preview contains no triangles")
            if preview.get("line_count", len(lines)) != len(lines):
                raise VerificationError("Preview line count mismatch")

            if preview["point_count"] != len(points):
                raise VerificationError("Preview point count mismatch")

            if preview["triangle_count"] != len(triangles):
                raise VerificationError("Preview triangle count mismatch")

            if any(
                not isinstance(line, list)
                or len(line) != 2
                or any(
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or index < 0
                    or index >= len(points)
                    for index in line
                )
                for line in lines
            ):
                raise VerificationError("Preview contains invalid line indices")

            if any(
                not isinstance(triangle, list)
                or len(triangle) != 3
                or any(
                    not isinstance(index, int)
                    or isinstance(index, bool)
                    or index < 0
                    or index >= len(points)
                    for index in triangle
                )
                for triangle in triangles
            ):
                raise VerificationError("Preview contains invalid triangle indices")

        except (
            OSError,
            UnicodeError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            raise VerificationError(f"Invalid geometry preview: {exc}") from exc

    @staticmethod
    def _verify_element_family(
        mesh: MeshResult,
        request: MeshRequest,
    ) -> None:
        metadata = mesh.metadata

        if metadata.element_types:
            actual_total = sum(metadata.element_types.values())

            if actual_total != metadata.element_count:
                raise VerificationError("Mesh element count mismatch")

        if request.settings.dimension in (MeshDimension.ONE_D, MeshDimension.TWO_D):
            prefix = {
                MeshElementFamily.LINE: "line",
                MeshElementFamily.TRIANGULAR: "triangle",
                MeshElementFamily.QUADRILATERAL: "quad",
            }[request.settings.element_family]
            other_prefixes = ("line", "triangle", "quad")
            relevant = [
                (name.lower(), count)
                for name, count in metadata.element_types.items()
                if count > 0
                and name.lower().startswith(other_prefixes)
                and (request.settings.dimension == 2 or name.lower().startswith("line"))
            ]
            # 2D includes boundary lines; only inspect 2D cells.
            if request.settings.dimension == MeshDimension.TWO_D:
                relevant = [
                    (name, count)
                    for name, count in relevant
                    if name.startswith(("triangle", "quad"))
                ]
            if not relevant or any(not name.startswith(prefix) for name, _ in relevant):
                raise VerificationError(
                    f"Requested {request.settings.element_family.value} "
                    f"mesh, but actual elements are {metadata.element_types}"
                )
            return

        # Prefer dimension-classified Gmsh metadata.
        volume_types = {
            name: count
            for name, count in metadata.volume_element_types.items()
            if count > 0
        }

        # Compatibility with older mesh result fixtures and
        # previously stored Gmsh metadata.
        if not volume_types:
            volume_names = (
                "tetrahedron",
                "hexahedron",
                "prism",
                "pyramid",
                "wedge",
                "trihedron",
            )

            volume_types = {
                name: count
                for name, count in metadata.element_types.items()
                if count > 0 and name.lower().startswith(volume_names)
            }

        if not volume_types:
            raise VerificationError("3D mesh contains no volume elements")

        if request.settings.element_family == MeshElementFamily.TETRAHEDRAL:
            expected_prefix = "tetrahedron"

        elif request.settings.element_family == MeshElementFamily.HEXAHEDRAL:
            expected_prefix = "hexahedron"

        else:
            raise VerificationError("Unsupported mesh element family")

        expected_count = sum(
            count
            for name, count in volume_types.items()
            if name.lower().startswith(expected_prefix)
        )

        unexpected_types = {
            name: count
            for name, count in volume_types.items()
            if not name.lower().startswith(expected_prefix)
        }

        if expected_count <= 0 or unexpected_types:
            raise VerificationError(
                f"Requested {request.settings.element_family.value} "
                "mesh, but actual volume element types are "
                f"{volume_types}"
            )

    def _verify_mesh(
        self,
        job: Job,
        result: dict[str, Any],
    ) -> None:
        try:
            mesh = MeshResult.model_validate(result)
            request = MeshRequest.model_validate(job.input)
        except ValueError as exc:
            raise VerificationError("Invalid mesh result or request") from exc

        if mesh.geometry_artifact_id != request.geometry_artifact_id:
            raise VerificationError("Mesh refers to an unexpected geometry")

        if mesh.metadata.node_count <= 0:
            raise VerificationError("Mesh contains no nodes")

        if mesh.metadata.element_count <= 0:
            raise VerificationError("Mesh contains no elements")

        self._verify_element_family(mesh, request)

        self._check_artifact(
            artifact_id=request.geometry_artifact_id,
            project_id=job.project_id,
            expected_type=ArtifactType.GEOMETRY,
            expected_suffix=".step",
        )

        self._check_artifact(
            artifact_id=mesh.artifact_id,
            project_id=job.project_id,
            expected_type=ArtifactType.MESH,
            expected_suffix=".msh",
            parent_id=request.geometry_artifact_id,
        )
