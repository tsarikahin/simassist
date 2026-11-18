from __future__ import annotations

import math
from pathlib import Path
from uuid import UUID, uuid4, uuid5

import gmsh
from pydantic import BaseModel, Field, computed_field
from simassist.core.models.artifact import (
    ArtifactCreate,
    ArtifactType,
)
from simassist.storage.base import ArtifactStore


class CadFace(BaseModel):
    geometry_revision_id: UUID
    face_key: str
    local_gmsh_tag: int
    area: float
    coordinate_units: str
    area_units: str
    bounds: tuple[float, float, float, float, float, float]
    geometric_type: str
    normal: tuple[float, float, float] | None = None
    normal_information: str

    @computed_field
    @property
    def bounds_min_xyz(self) -> tuple[float, float, float]:
        return self.bounds[:3]

    @computed_field
    @property
    def bounds_max_xyz(self) -> tuple[float, float, float]:
        return self.bounds[3:]


class CadEntity(BaseModel):
    geometry_revision_id: UUID
    entity_id: UUID
    entity_key: str
    dimension: int = Field(ge=0, le=3)
    tag: int = Field(gt=0)
    label: str
    geometric_type: str
    coordinate_units: str
    bounds: tuple[float, float, float, float, float, float]
    coordinates: tuple[float, float, float] | None = None
    length: float | None = None
    area: float | None = None
    volume: float | None = None
    measure_units: str | None = None
    normal: tuple[float, float, float] | None = None
    normal_information: str | None = None
    boundary_entity_keys: list[str] = Field(default_factory=list)
    owner_body_keys: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def bounds_min_xyz(self) -> tuple[float, float, float]:
        return self.bounds[:3]

    @computed_field
    @property
    def bounds_max_xyz(self) -> tuple[float, float, float]:
        return self.bounds[3:]


def entity_key(revision: UUID, dimension: int, tag: int) -> str:
    kind = ("vertex", "edge", "face", "body")[dimension]
    return f"{revision}:{kind}:{tag}"


class GeometryPreview(BaseModel):
    points: list[tuple[float, float, float]]
    lines: list[tuple[int, int]] = Field(default_factory=list)
    triangles: list[tuple[int, int, int]]
    point_count: int = Field(ge=0)
    triangle_count: int = Field(ge=0)
    line_count: int = Field(default=0, ge=0)
    dimension: int = Field(default=3, ge=1, le=3)
    geometry_revision_id: UUID | None = None
    triangle_face_keys: list[str] = Field(default_factory=list)
    faces: list[CadFace] = Field(default_factory=list)
    topology_version: int = 0
    entities: list[CadEntity] = Field(default_factory=list)
    vertex_point_indices: list[int] = Field(default_factory=list)
    vertex_entity_keys: list[str] = Field(default_factory=list)
    edge_segments: list[tuple[int, int]] = Field(default_factory=list)
    edge_entity_keys: list[str] = Field(default_factory=list)


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

    def generate(
        self, geometry_artifact_id: UUID, coordinate_units: str = "unknown"
    ) -> UUID:
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
            cad_entities = self._inspect_entities(
                geometry_artifact_id, coordinate_units
            )
            vertex_point_indices = []
            vertex_entity_keys = []
            edge_segments = []
            edge_entity_keys = []
            for entity in cad_entities:
                if entity.dimension == 0:
                    tags, _, _ = gmsh.model.mesh.getNodes(0, entity.tag)
                    if len(tags) == 1 and int(tags[0]) in tag_to_index:
                        vertex_point_indices.append(tag_to_index[int(tags[0])])
                        vertex_entity_keys.append(entity.entity_key)
                elif entity.dimension == 1:
                    types, _, groups = gmsh.model.mesh.getElements(1, entity.tag)
                    for cell_type, nodes in zip(types, groups, strict=True):
                        if int(cell_type) != 1:
                            raise ValueError("Unsupported CAD edge preview cell type")
                        for i in range(0, len(nodes), 2):
                            edge_segments.append(
                                (
                                    tag_to_index[int(nodes[i])],
                                    tag_to_index[int(nodes[i + 1])],
                                )
                            )
                            edge_entity_keys.append(entity.entity_key)
            lines: list[tuple[int, int]] = []
            triangles: list[tuple[int, int, int]] = []
            triangle_face_keys: list[str] = []
            faces: list[CadFace] = []
            by_key = {entity.entity_key: entity for entity in cad_entities}
            for dim, tag in sorted(gmsh.model.getEntities(min(dimension, 2))):
                face_key = f"{geometry_artifact_id}:face:{tag}"
                if dim == 2:
                    entity = by_key[face_key]
                    faces.append(
                        CadFace(
                            geometry_revision_id=geometry_artifact_id,
                            face_key=face_key,
                            local_gmsh_tag=tag,
                            area=entity.area,
                            coordinate_units=coordinate_units,
                            area_units=entity.measure_units,
                            bounds=entity.bounds,
                            geometric_type=entity.geometric_type,
                            normal=entity.normal,
                            normal_information=entity.normal_information,
                        )
                    )
                before = len(triangles)
                element_types, _, element_nodes = gmsh.model.mesh.getElements(dim, tag)
                for element_type, nodes in zip(
                    element_types, element_nodes, strict=True
                ):
                    self._append_cells(
                        dimension, element_type, nodes, tag_to_index, lines, triangles
                    )
                triangle_face_keys.extend([face_key] * (len(triangles) - before))
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
                geometry_revision_id=geometry_artifact_id,
                triangle_face_keys=triangle_face_keys,
                faces=faces,
                topology_version=1,
                entities=cad_entities,
                vertex_point_indices=vertex_point_indices,
                vertex_entity_keys=vertex_entity_keys,
                edge_segments=edge_segments,
                edge_entity_keys=edge_entity_keys,
            )

        finally:
            gmsh.finalize()

        output_dir = self.workspace / str(uuid4())
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / "preview.json"
        output_path.write_text(preview.model_dump_json(), encoding="utf-8")
        return self.artifact_store.save(
            ArtifactCreate(
                project_id=self.project_id,
                type=ArtifactType.GEOMETRY_PREVIEW,
                source_path=output_path,
                parent_ids=[geometry_artifact_id],
            )
        ).id

    @staticmethod
    def _inspect_entities(revision: UUID, units: str) -> list[CadEntity]:
        entities = []
        for dimension in range(4):
            for index, (_, tag) in enumerate(
                sorted(gmsh.model.getEntities(dimension)), 1
            ):
                kind = ("Vertex", "Edge", "Face", "Body")[dimension]
                values = {}
                if dimension == 0:
                    values["coordinates"] = tuple(
                        float(v) for v in gmsh.model.getValue(0, tag, [])
                    )
                else:
                    measure = ("", "length", "area", "volume")[dimension]
                    values[measure] = float(gmsh.model.occ.getMass(dimension, tag))
                    values["measure_units"] = (
                        "unknown"
                        if units == "unknown"
                        else units
                        if dimension == 1
                        else f"{units}^{dimension}"
                    )
                geometric_type = gmsh.model.getType(dimension, tag)
                if dimension == 2:
                    if geometric_type == "Plane":
                        lower, upper = gmsh.model.getParametrizationBounds(2, tag)
                        uv = [
                            (float(a) + float(b)) / 2
                            for a, b in zip(lower, upper, strict=True)
                        ]
                        values["normal"] = tuple(
                            float(v) for v in gmsh.model.getNormal(tag, uv)
                        )
                        values["normal_information"] = (
                            "Constant CAD parametric normal; not guaranteed outward"
                        )
                    else:
                        values["normal_information"] = (
                            "Normal varies over curved face; no global normal reported"
                        )
                boundaries = (
                    gmsh.model.getBoundary(
                        [(dimension, tag)], combined=False, oriented=False
                    )
                    if dimension
                    else []
                )
                owners = gmsh.model.getAdjacencies(2, tag)[0] if dimension == 2 else []
                entities.append(
                    CadEntity(
                        geometry_revision_id=revision,
                        entity_id=uuid5(revision, f"{dimension}:{tag}"),
                        entity_key=entity_key(revision, dimension, tag),
                        dimension=dimension,
                        tag=tag,
                        label=f"{kind} {index}",
                        geometric_type=geometric_type,
                        coordinate_units=units,
                        bounds=gmsh.model.getBoundingBox(dimension, tag),
                        boundary_entity_keys=sorted(
                            {entity_key(revision, d, abs(t)) for d, t in boundaries}
                        ),
                        owner_body_keys=sorted(
                            {entity_key(revision, 3, int(t)) for t in owners}
                        ),
                        **values,
                    )
                )
        return entities

    @staticmethod
    def _append_cells(dimension, element_type, nodes, tag_to_index, lines, triangles):
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
                triangles.append(tuple(tag_to_index[int(v)] for v in nodes[i : i + 3]))
        elif dimension >= 2 and nodes_per_element == 4:
            for i in range(0, len(nodes), 4):
                a, b, c, d = (tag_to_index[int(v)] for v in nodes[i : i + 4])
                triangles.extend([(a, b, c), (a, c, d)])
        else:
            raise ValueError("Unsupported geometry preview cell type")
