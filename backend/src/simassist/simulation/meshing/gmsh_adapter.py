from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import gmsh
from simassist.core.models.artifact import (
    ArtifactCreate,
    ArtifactType,
)
from simassist.core.models.mesh import (
    MeshMetadata,
    MeshRequest,
    MeshResult,
)
from simassist.storage.base import ArtifactStore


class GmshMeshingAdapter:
    """Generic Gmsh meshing engine for CAD artifacts."""

    def __init__(
        self,
        workspace: Path,
        artifact_store: ArtifactStore,
        project_id: UUID,
    ):
        self.workspace = workspace
        self.artifact_store = artifact_store
        self.project_id = project_id

    @property
    def name(self) -> str:
        return "gmsh"

    def generate(self, request: MeshRequest) -> MeshResult:
        geometry = self.artifact_store.get(request.geometry_artifact_id)

        if geometry.project_id != self.project_id:
            raise ValueError("Geometry belongs to a different project")

        if geometry.type != ArtifactType.GEOMETRY:
            raise ValueError("Input artifact must be a geometry")

        geometry_path = self.artifact_store.resolve_path(geometry.id)

        if geometry_path.suffix.lower() not in {".step", ".stp"}:
            raise ValueError("Gmsh adapter currently requires STEP geometry")

        job_id = uuid4()
        output_dir = self.workspace / str(job_id)
        output_dir.mkdir(parents=True, exist_ok=True)

        mesh_path = output_dir / "mesh.msh"

        gmsh.initialize()

        try:
            gmsh.model.add(f"mesh_{job_id.hex}")

            gmsh.model.occ.importShapes(str(geometry_path))
            gmsh.model.occ.synchronize()

            settings = request.settings

            gmsh.option.setNumber(
                "Mesh.MeshSizeMin",
                settings.min_size,
            )
            gmsh.option.setNumber(
                "Mesh.MeshSizeMax",
                settings.max_size,
            )

            if settings.algorithm is not None:
                option = (
                    "Mesh.Algorithm3D" if settings.dimension == 3 else "Mesh.Algorithm"
                )
                gmsh.option.setNumber(
                    option,
                    settings.algorithm,
                )

            gmsh.model.mesh.generate(int(settings.dimension))

            metadata = self._get_metadata()

            gmsh.option.setNumber(
                "Mesh.MshFileVersion",
                4.1,
            )
            gmsh.write(str(mesh_path))

        finally:
            gmsh.finalize()

        artifact = self.artifact_store.save(
            ArtifactCreate(
                project_id=self.project_id,
                type=ArtifactType.MESH,
                source_path=mesh_path,
                parent_ids=[geometry.id],
            )
        )

        return MeshResult(
            engine=self.name,
            artifact_id=artifact.id,
            geometry_artifact_id=geometry.id,
            metadata=metadata,
        )

    @staticmethod
    def _get_metadata() -> MeshMetadata:
        node_tags, _, _ = gmsh.model.mesh.getNodes()

        element_types, element_tags, _ = gmsh.model.mesh.getElements()

        element_counts: dict[str, int] = {}

        for element_type, tags in zip(
            element_types,
            element_tags,
        ):
            name, *_ = gmsh.model.mesh.getElementProperties(int(element_type))
            element_counts[name] = element_counts.get(name, 0) + len(tags)

        return MeshMetadata(
            node_count=len(node_tags),
            element_count=sum(element_counts.values()),
            element_types=element_counts,
        )
