from __future__ import annotations

import math
from pathlib import Path
from uuid import UUID, uuid4

import gmsh
from pydantic import BaseModel, Field
from simassist.core.models.artifact import (
    ArtifactCreate,
    ArtifactType,
)
from simassist.storage.base import ArtifactStore


class GeometryPreview(BaseModel):
    points: list[tuple[float, float, float]]
    triangles: list[tuple[int, int, int]]
    point_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)


class GmshPreviewService:
    """Generate renderable surface previews from CAD artifacts."""

    def __init__(
        self,
        workspace: Path,
        artifact_store: ArtifactStore,
        project_id: UUID,
    ):
        self.workspace = workspace
        self.artifact_store = artifact_store
        self.project_id = project_id

    def generate(self, geometry_artifact_id: UUID) -> UUID:
        artifact = self.artifact_store.get(geometry_artifact_id)

        if artifact.project_id != self.project_id:
            raise ValueError("Geometry belongs to another project")

        if artifact.type != ArtifactType.GEOMETRY:
            raise ValueError("Artifact is not a geometry")

        geometry_path = self.artifact_store.resolve_path(geometry_artifact_id)

        if geometry_path.suffix.lower() not in {".step", ".stp"}:
            raise ValueError("Only STEP input is currently supported")

        gmsh.initialize()

        try:
            gmsh.model.add("geometry_preview")

            gmsh.model.occ.importShapes(str(geometry_path))
            gmsh.model.occ.synchronize()

            volumes = gmsh.model.getEntities(3)

            if not volumes:
                raise ValueError("No solid volumes found")

            bounds = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in volumes]

            xmin = min(b[0] for b in bounds)
            ymin = min(b[1] for b in bounds)
            zmin = min(b[2] for b in bounds)
            xmax = max(b[3] for b in bounds)
            ymax = max(b[4] for b in bounds)
            zmax = max(b[5] for b in bounds)

            diagonal = math.dist(
                (xmin, ymin, zmin),
                (xmax, ymax, zmax),
            )

            if diagonal <= 0:
                raise ValueError("Invalid geometry dimensions")

            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.MeshSizeMin", diagonal / 200)
            gmsh.option.setNumber("Mesh.MeshSizeMax", diagonal / 20)

            # Only triangulate the boundary surfaces.
            gmsh.model.mesh.generate(2)

            node_tags, coordinates, _ = gmsh.model.mesh.getNodes()

            points = [
                (
                    float(coordinates[i]),
                    float(coordinates[i + 1]),
                    float(coordinates[i + 2]),
                )
                for i in range(0, len(coordinates), 3)
            ]

            tag_to_index = {int(tag): index for index, tag in enumerate(node_tags)}

            element_types, _, element_nodes = gmsh.model.mesh.getElements(dim=2)

            triangles: list[tuple[int, int, int]] = []

            for element_type, nodes in zip(element_types, element_nodes, strict=True):
                properties = gmsh.model.mesh.getElementProperties(int(element_type))
                dimension = int(properties[1])
                nodes_per_element = int(properties[3])

                if dimension != 2 or nodes_per_element != 3:
                    raise ValueError("Preview requires first-order triangles")

                for i in range(0, len(nodes), 3):
                    triangles.append(
                        (
                            tag_to_index[int(nodes[i])],
                            tag_to_index[int(nodes[i + 1])],
                            tag_to_index[int(nodes[i + 2])],
                        )
                    )

            if not triangles:
                raise ValueError("No surface triangles generated")

            preview = GeometryPreview(
                points=points,
                triangles=triangles,
                point_count=len(points),
                triangle_count=len(triangles),
            )

        finally:
            gmsh.finalize()

        output_dir = self.workspace / str(uuid4())
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "preview.json"
        output_path.write_text(
            preview.model_dump_json(),
            encoding="utf-8",
        )

        preview_artifact = self.artifact_store.save(
            ArtifactCreate(
                project_id=self.project_id,
                type=ArtifactType.GEOMETRY_PREVIEW,
                source_path=output_path,
                parent_ids=[geometry_artifact_id],
            )
        )

        return preview_artifact.id
