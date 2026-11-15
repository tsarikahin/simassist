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
    lines: list[tuple[int, int]] = Field(default_factory=list)
    triangles: list[tuple[int, int, int]]
    point_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)
    line_count: int = Field(default=0, ge=0)
    dimension: int = Field(default=3, ge=1, le=3)


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
            surfaces = gmsh.model.getEntities(2)
            curves = gmsh.model.getEntities(1)
            dimension = 3 if volumes else 2 if surfaces else 1 if curves else 0
            if dimension == 0:
                raise ValueError("Geometry has no meshing entities")
            entities = gmsh.model.getEntities(dimension)
            bounds = [gmsh.model.getBoundingBox(d, tag) for d, tag in entities]
            diagonal = math.dist(
                (
                    min(b[0] for b in bounds),
                    min(b[1] for b in bounds),
                    min(b[2] for b in bounds),
                ),
                (
                    max(b[3] for b in bounds),
                    max(b[4] for b in bounds),
                    max(b[5] for b in bounds),
                ),
            )
            if diagonal <= 0:
                raise ValueError("Invalid geometry dimensions")
            gmsh.option.setNumber("Mesh.ElementOrder", 1)
            gmsh.option.setNumber("Mesh.MeshSizeMin", diagonal / 200)
            gmsh.option.setNumber("Mesh.MeshSizeMax", diagonal / 20)
            gmsh.model.mesh.generate(min(dimension, 2))

            node_tags, coordinates, _ = gmsh.model.mesh.getNodes()
            points = [
                (
                    float(coordinates[i]),
                    float(coordinates[i + 1]),
                    float(coordinates[i + 2]),
                )
                for i in range(0, len(coordinates), 3)
            ]
            tag_to_index = {int(tag): i for i, tag in enumerate(node_tags)}
            lines: list[tuple[int, int]] = []
            triangles: list[tuple[int, int, int]] = []
            element_types, _, element_nodes = gmsh.model.mesh.getElements(
                dim=min(dimension, 2)
            )
            for element_type, nodes in zip(element_types, element_nodes, strict=True):
                properties = gmsh.model.mesh.getElementProperties(int(element_type))
                nodes_per_element = int(properties[3])
                if dimension == 1 and nodes_per_element == 2:
                    for i in range(0, len(nodes), 2):
                        lines.append(
                            (
                                tag_to_index[int(nodes[i])],
                                tag_to_index[int(nodes[i + 1])],
                            )
                        )
                elif dimension >= 2 and nodes_per_element == 3:
                    for i in range(0, len(nodes), 3):
                        triangles.append(
                            tuple(tag_to_index[int(v)] for v in nodes[i : i + 3])
                        )
                elif dimension >= 2 and nodes_per_element == 4:
                    for i in range(0, len(nodes), 4):
                        a, b, c, d = (tag_to_index[int(v)] for v in nodes[i : i + 4])
                        triangles.extend([(a, b, c), (a, c, d)])
                else:
                    raise ValueError("Unsupported geometry preview cell type")
            if not (lines if dimension == 1 else triangles):
                raise ValueError("No preview elements generated")

            preview = GeometryPreview(
                points=points,
                triangles=triangles,
                lines=lines,
                line_count=len(lines),
                dimension=dimension,
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
