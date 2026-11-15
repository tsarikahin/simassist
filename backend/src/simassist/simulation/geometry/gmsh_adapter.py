from __future__ import annotations

from pathlib import Path
from uuid import UUID

import gmsh
from simassist.core.models.artifact import ArtifactCreate, ArtifactType
from simassist.core.models.geometry import (
    BooleanGeometry,
    CADImportGeometry,
    GeometryMetadata,
    GeometryResult,
    GeometrySpec,
    PrimitiveGeometry,
    PrimitiveType,
    Vector3D,
)
from simassist.storage.base import ArtifactStore


class GmshGeometryAdapter:
    """Geometry engine implementation using Gmsh OpenCASCADE."""

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

    def create(self, spec: GeometrySpec) -> GeometryResult:
        """Create geometry and register its STEP artifact."""

        output_dir = self.workspace / str(spec.id)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_path = output_dir / "geometry.step"

        gmsh.initialize()

        try:
            gmsh.model.add(spec.name)

            definition = spec.definition

            if isinstance(definition, PrimitiveGeometry):
                self._create_primitive(definition)

            elif isinstance(definition, CADImportGeometry):
                raise NotImplementedError("CAD import is not implemented yet.")

            elif isinstance(definition, BooleanGeometry):
                raise NotImplementedError("Boolean operations are not implemented yet.")

            else:
                raise TypeError(f"Unsupported geometry definition: {type(definition)}")

            gmsh.model.occ.synchronize()

            metadata = self._get_metadata()

            gmsh.write(str(output_path))

        finally:
            gmsh.finalize()

        artifact = self.artifact_store.save(
            ArtifactCreate(
                project_id=self.project_id,
                type=ArtifactType.GEOMETRY,
                source_path=output_path,
            )
        )

        return GeometryResult(
            geometry_id=spec.id,
            engine=self.name,
            artifact_id=artifact.id,
            metadata=metadata,
        )

    def inspect(self, geometry: GeometryResult) -> GeometryMetadata:
        """Inspect geometry using the registered artifact."""

        geometry_path = self.artifact_store.resolve_path(geometry.artifact_id)

        gmsh.initialize()

        try:
            gmsh.model.add("inspect_geometry")

            gmsh.model.occ.importShapes(str(geometry_path))
            gmsh.model.occ.synchronize()

            return self._get_metadata()

        finally:
            gmsh.finalize()

    @staticmethod
    def _create_primitive(definition: PrimitiveGeometry) -> None:
        """Create a supported geometric primitive."""

        parameters = definition.parameters
        origin = definition.origin

        if definition.primitive == PrimitiveType.BOX:
            gmsh.model.occ.addBox(
                origin.x,
                origin.y,
                origin.z,
                parameters["length"],
                parameters["width"],
                parameters["height"],
            )

        elif definition.primitive == PrimitiveType.LINE:
            length = parameters["length"]
            p0 = gmsh.model.occ.addPoint(origin.x, origin.y, origin.z)
            p1 = gmsh.model.occ.addPoint(origin.x + length, origin.y, origin.z)
            gmsh.model.occ.addLine(p0, p1)

        elif definition.primitive in (PrimitiveType.SQUARE, PrimitiveType.RECTANGLE):
            gmsh.model.occ.addRectangle(
                origin.x,
                origin.y,
                origin.z,
                parameters["size"]
                if definition.primitive == PrimitiveType.SQUARE
                else parameters["width"],
                parameters["size"]
                if definition.primitive == PrimitiveType.SQUARE
                else parameters["height"],
            )

        elif definition.primitive == PrimitiveType.DISK:
            gmsh.model.occ.addDisk(
                origin.x,
                origin.y,
                origin.z,
                parameters["radius"],
                parameters["radius"],
            )

        elif definition.primitive == PrimitiveType.CYLINDER:
            gmsh.model.occ.addCylinder(
                origin.x,
                origin.y,
                origin.z,
                0.0,
                0.0,
                parameters["height"],
                parameters["radius"],
            )

        elif definition.primitive == PrimitiveType.SPHERE:
            gmsh.model.occ.addSphere(
                origin.x,
                origin.y,
                origin.z,
                parameters["radius"],
            )

        else:
            raise ValueError(f"Unsupported primitive: {definition.primitive}")

    @staticmethod
    def _get_metadata() -> GeometryMetadata:
        """Extract geometric metadata from the current Gmsh model."""

        volumes = gmsh.model.getEntities(dim=3)
        surfaces = gmsh.model.getEntities(dim=2)
        curves = gmsh.model.getEntities(dim=1)
        dimension = 3 if volumes else 2 if surfaces else 1 if curves else 0
        if dimension == 0:
            raise ValueError("Geometry contains no curves, surfaces or volumes")
        entities = gmsh.model.getEntities(dim=dimension)
        bounds = [gmsh.model.getBoundingBox(dim, tag) for dim, tag in entities]
        return GeometryMetadata(
            dimension=dimension,
            curve_count=len(curves),
            volume_count=len(volumes),
            surface_count=len(surfaces),
            bounding_box_min=Vector3D(
                x=min(b[0] for b in bounds),
                y=min(b[1] for b in bounds),
                z=min(b[2] for b in bounds),
            ),
            bounding_box_max=Vector3D(
                x=max(b[3] for b in bounds),
                y=max(b[4] for b in bounds),
                z=max(b[5] for b in bounds),
            ),
        )
