from __future__ import annotations

import json
import math
from typing import Any, Literal
from uuid import UUID

from pydantic import ValidationError

from simassist.agents.tools.geometry import GeometryTools
from simassist.core.models.geometry import GeometrySpec, PrimitiveGeometry
from simassist.core.models.mesh import MeshRequest, MeshSettings
from simassist.jobs.models import JobType
from simassist.projects.context import ProjectContextRepository

PrimitiveName = Literal[
    "line", "square", "rectangle", "disk", "box", "cylinder", "sphere"
]
LengthUnitName = Literal["mm", "cm", "m", "in"]
ElementFamilyName = Literal[
    "line", "triangular", "quadrilateral", "tetrahedral", "hexahedral"
]

GEOMETRY_PARAMETERS: dict[str, set[str]] = {
    "box": {"length", "width", "height"},
    "cylinder": {"radius", "height"},
    "sphere": {"radius"},
    "line": {"length"},
    "square": {"size"},
    "rectangle": {"width", "height"},
    "disk": {"radius"},
}
BOX_ALIASES = {"dx": "length", "dy": "width", "dz": "height"}


class SimulationTools:
    """Agent-facing tools for engineering simulations."""

    def __init__(
        self,
        geometry: GeometryTools,
        project_context: ProjectContextRepository | None = None,
    ) -> None:
        self.geometry = geometry
        self.project_context = project_context
        self.submitted_job_ids: list[str] = []

    @staticmethod
    def _error(message: str, **details: object) -> str:
        return json.dumps({"ok": False, "error": message, **details})

    @staticmethod
    def _validate_element_family(element_family: str, dimension: int) -> str | None:
        if element_family == "hexahedral":
            return (
                "Hexahedral meshing is not supported by the current Gmsh engine. "
                "No job was submitted. Ask before switching to tetrahedral."
            )
        expected = {
            1: {"line"},
            2: {"triangular", "quadrilateral"},
            3: {"tetrahedral"},
        }
        if dimension not in expected:
            return "Mesh dimension must be 1, 2 or 3"
        if element_family not in expected[dimension]:
            return f"Unsupported {dimension}D element family: {element_family}"
        return None

    @staticmethod
    def _normalize_parameters(
        primitive: str, parameters: dict[str, float]
    ) -> tuple[dict[str, float] | None, str | None]:
        required = GEOMETRY_PARAMETERS.get(primitive)
        if required is None:
            return None, f"Unsupported primitive: {primitive}"

        normalized = dict(parameters)
        if primitive == "box":
            for alias, canonical in BOX_ALIASES.items():
                if alias in normalized:
                    if canonical in normalized:
                        return None, f"Conflicting parameters: {alias} and {canonical}"
                    normalized[canonical] = normalized.pop(alias)

        if set(normalized) != required:
            return None, f"{primitive} requires parameters {sorted(required)}"
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in normalized.values()
        ):
            return None, "Dimensions must be positive finite numbers"
        return normalized, None

    @staticmethod
    def _validate_mesh_settings(
        dimension: int,
        min_size: float,
        max_size: float,
        element_family: str | None,
    ) -> tuple[MeshSettings | None, str | None]:
        if element_family is None:
            element_family = {1: "line", 2: "triangular", 3: "tetrahedral"}.get(
                dimension
            )
        family_error = SimulationTools._validate_element_family(
            element_family, dimension
        )
        if family_error:
            return None, family_error
        try:
            settings = MeshSettings(
                dimension=dimension,
                min_size=min_size,
                max_size=max_size,
                element_family=element_family,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            return None, str(exc)
        return settings, None

    def list_geometry_capabilities(self) -> str:
        """List supported geometry primitives, parameters, and meshing support."""
        return json.dumps(
            {
                "supported": {
                    "box": ["length", "width", "height"],
                    "cylinder": ["radius", "height"],
                    "sphere": ["radius"],
                    "line": ["length"],
                    "square": ["size"],
                    "rectangle": ["width", "height"],
                    "disk": ["radius"],
                },
                "aliases": {"box": BOX_ALIASES},
                "units": ["mm", "cm", "m", "in"],
                "constraints": (
                    "All dimensions must be positive. "
                    "Primitive and inline boolean CSG creation are implemented. "
                    "Boolean operations on existing STEP artifacts are not yet supported."
                ),
                "boolean_csg": {
                    "operations": ["cut", "fuse", "intersect"],
                    "operands": "At least two inline 2D or 3D primitive geometries",
                    "example": "outer disk minus concentric inner disk for annulus",
                },
                "meshing": {
                    "engine": "gmsh",
                    "supported_3d_element_families": ["tetrahedral"],
                    "unsupported_3d_element_families": ["hexahedral"],
                    "supported_1d_elements": ["line"],
                    "supported_2d_elements": ["triangular", "quadrilateral"],
                },
            }
        )

    def get_active_geometry(self) -> str:
        """Return the active geometry in this project, or explain if none is selected."""
        if self.project_context is None:
            return self._error("Project context is not configured")

        context = self.project_context.get(self.geometry.project_id)
        if context.active_geometry_job_id is None:
            return self._error(
                "No active geometry is selected. Select a completed geometry "
                "in Project Explorer before meshing."
            )

        status = self.geometry.get_job_status(str(context.active_geometry_job_id))
        if not status.get("ok") or status.get("job_type") != JobType.GEOMETRY_CREATE:
            return self._error("The active geometry job is unavailable")
        if status.get("status") != "completed":
            return self._error("The active geometry job is not completed")

        return json.dumps(
            {
                "ok": True,
                "geometry_job_id": str(context.active_geometry_job_id),
                "geometry_artifact_id": str(context.active_geometry_artifact_id),
                "status": status["status"],
            }
        )

    def create_geometry(
        self,
        name: str,
        primitive: PrimitiveName,
        parameters: dict[str, float],
        units: LengthUnitName = "mm",
    ) -> str:
        """Submit a geometry creation job.

        Args:
            name: Descriptive geometry name.
            primitive: Box, cylinder, or sphere.
            parameters: Box uses length/width/height; cylinder radius/height;
                sphere radius.
            units: Geometry length unit.
        """
        normalized, error = self._normalize_parameters(primitive, parameters)
        if error or normalized is None:
            return self._error(error or "Invalid geometry parameters")

        result = self.geometry.create_geometry(
            {
                "name": name,
                "units": units,
                "definition": {
                    "source": "primitive",
                    "primitive": primitive,
                    "parameters": normalized,
                },
            }
        )
        if result.get("ok") and result.get("job_id"):
            self.submitted_job_ids.append(result["job_id"])
        return json.dumps(result)

    def generate_mesh(
        self,
        geometry_job_id: str | None = None,
        dimension: Literal[1, 2, 3] | None = None,
        min_size: float = 1.0,
        max_size: float = 5.0,
        element_family: ElementFamilyName | None = None,
    ) -> str:
        """Mesh a completed geometry, defaulting to the selected active geometry.

        Args:
            geometry_job_id: Existing geometry job ID. Omit ONLY when the user
                refers to the current/active/selected geometry.
            dimension: 2D surface or 3D volume mesh.
            min_size: Minimum mesh size in geometry units.
            max_size: Maximum mesh size in geometry units.
            element_family: Tetrahedral supported; hexahedral unsupported.
                Never silently substitute tet for hex.
        """
        # Reject unsupported 3D hex before any geometry lookup or job submission.
        if element_family == "hexahedral":
            return self._error(
                "Hexahedral meshing is not supported by the current Gmsh engine. "
                "No job was submitted. Ask before switching to tetrahedral.",
                requested_element_family=element_family,
            )

        if (
            not isinstance(min_size, (int, float))
            or not isinstance(max_size, (int, float))
            or isinstance(min_size, bool)
            or isinstance(max_size, bool)
            or not math.isfinite(min_size)
            or not math.isfinite(max_size)
            or min_size <= 0
            or max_size <= 0
            or min_size > max_size
        ):
            return self._error("Invalid mesh element size settings")

        if geometry_job_id is None:
            active = json.loads(self.get_active_geometry())
            if not active.get("ok"):
                return json.dumps(active)
            geometry_job_id = active["geometry_job_id"]

        try:
            UUID(geometry_job_id)
        except (ValueError, TypeError):
            return self._error("Invalid geometry job ID")

        geometry_status = self.geometry.get_job_status(geometry_job_id)
        if not geometry_status.get("ok"):
            return json.dumps(geometry_status)
        if geometry_status.get("job_type") != JobType.GEOMETRY_CREATE:
            return self._error("The provided job is not a geometry job")
        if geometry_status.get("status") != "completed":
            return self._error(
                "Geometry job is not completed yet",
                status=geometry_status.get("status"),
                geometry_job_id=geometry_job_id,
            )

        geometry_result = geometry_status.get("result") or {}
        geometry_metadata = geometry_result.get("metadata") or {}
        geometry_dimension = geometry_metadata.get("dimension")
        if geometry_dimension is None:
            geometry_dimension = (
                3
                if geometry_metadata.get("volume_count", 0)
                else 2
                if geometry_metadata.get("surface_count", 0)
                else 3
            )
        if dimension is None:
            dimension = int(geometry_dimension)
        if int(dimension) != int(geometry_dimension):
            return self._error(
                f"Selected geometry is {geometry_dimension}D, but requested mesh is {dimension}D"
            )
        settings, error = self._validate_mesh_settings(
            dimension, min_size, max_size, element_family
        )
        if error or settings is None:
            return self._error(error or "Invalid mesh settings")

        artifact_id = geometry_result.get("artifact_id")
        if not artifact_id:
            return self._error("Geometry job has no artifact ID")

        try:
            request = MeshRequest(
                geometry_artifact_id=UUID(str(artifact_id)),
                settings=settings,
            )
            job = self.geometry.job_manager.submit(
                project_id=self.geometry.project_id,
                job_type=JobType.MESH_GENERATE,
                payload=request.model_dump(mode="json"),
            )
        except (ValueError, TypeError) as exc:
            return self._error(str(exc))

        self.submitted_job_ids.append(str(job.id))
        return json.dumps(
            {
                "ok": True,
                "job_id": str(job.id),
                "job_type": job.type.value,
                "status": job.status.value,
                "geometry_artifact_id": str(request.geometry_artifact_id),
                "element_family": settings.element_family.value,
                "message": "Mesh generation job submitted",
            }
        )

    def create_geometry_and_mesh(
        self,
        name: str,
        primitive: PrimitiveName,
        parameters: dict[str, float],
        units: LengthUnitName = "mm",
        dimension: Literal[1, 2, 3] | None = None,
        min_size: float = 1.0,
        max_size: float = 5.0,
        element_family: ElementFamilyName | None = None,
    ) -> str:
        """Submit one geometry-to-mesh workflow with dependency management.

        Args:
            name: Geometry name.
            primitive: Box, cylinder, or sphere.
            parameters: Primitive dimensions.
            units: Geometry length unit.
            dimension: 2D or 3D mesh dimension.
            min_size: Minimum mesh size.
            max_size: Maximum mesh size.
            element_family: Tetrahedral supported; hexahedral rejected.
        """
        primitive_dimension = {
            "line": 1,
            "square": 2,
            "rectangle": 2,
            "disk": 2,
            "box": 3,
            "cylinder": 3,
            "sphere": 3,
        }.get(primitive)
        if primitive_dimension is None:
            return self._error(f"Unsupported primitive: {primitive}")
        if dimension is None:
            dimension = primitive_dimension
        if dimension != primitive_dimension:
            return self._error(
                f"{primitive} is {primitive_dimension}D and cannot be meshed as {dimension}D"
            )
        settings, settings_error = self._validate_mesh_settings(
            dimension, min_size, max_size, element_family
        )
        if settings_error or settings is None:
            return self._error(
                settings_error or "Invalid mesh settings",
                requested_element_family=element_family,
                supported_element_families=["tetrahedral"],
            )

        normalized, parameter_error = self._normalize_parameters(primitive, parameters)
        if parameter_error or normalized is None:
            return self._error(parameter_error or "Invalid geometry parameters")

        try:
            geometry_spec = GeometrySpec.model_validate(
                {
                    "name": name,
                    "units": units,
                    "definition": {
                        "source": "primitive",
                        "primitive": primitive,
                        "parameters": normalized,
                    },
                }
            )
        except (ValidationError, ValueError) as exc:
            return self._error(str(exc))

        geometry_job, mesh_job = self.geometry.job_manager.submit_geometry_mesh(
            project_id=self.geometry.project_id,
            geometry_payload=geometry_spec.model_dump(mode="json"),
            mesh_settings=settings.model_dump(mode="json"),
        )
        self.submitted_job_ids.extend([str(geometry_job.id), str(mesh_job.id)])
        return json.dumps(
            {
                "ok": True,
                "message": "Geometry and mesh workflow submitted",
                "geometry_job_id": str(geometry_job.id),
                "mesh_job_id": str(mesh_job.id),
                "status": "queued",
                "element_family": settings.element_family.value,
                "workflow": [
                    {"job_id": str(geometry_job.id), "type": geometry_job.type.value},
                    {
                        "job_id": str(mesh_job.id),
                        "type": mesh_job.type.value,
                        "depends_on": str(geometry_job.id),
                    },
                ],
            }
        )

    @classmethod
    def _build_csg_spec(
        cls,
        name: str,
        operation: str,
        operands: list[dict[str, Any]],
        units: str,
    ) -> tuple[GeometrySpec | None, int | None, str | None]:
        if operation not in {"cut", "fuse", "intersect"}:
            return None, None, f"Unsupported boolean operation: {operation}"
        if not isinstance(operands, list) or len(operands) < 2:
            return None, None, "At least two operands are required"
        if len(operands) > 16:
            return None, None, "At most 16 inline boolean operands are supported"

        primitive_dimensions = {
            "line": 1,
            "square": 2,
            "rectangle": 2,
            "disk": 2,
            "box": 3,
            "cylinder": 3,
            "sphere": 3,
        }
        normalized: list[dict[str, Any]] = []
        dims: set[int] = set()
        for index, operand in enumerate(operands):
            if not isinstance(operand, dict):
                return None, None, f"Operand {index} must be an object"
            if set(operand) - {"primitive", "parameters", "origin"}:
                return None, None, f"Unexpected operand {index} fields"
            primitive = operand.get("primitive")
            params = operand.get("parameters")
            if not isinstance(primitive, str) or not isinstance(params, dict):
                return None, None, f"Operand {index} needs primitive and parameters"
            checked, error = cls._normalize_parameters(primitive, params)
            if error or checked is None:
                return None, None, f"Operand {index}: {error}"
            dims.add(primitive_dimensions[primitive])
            origin = operand.get("origin", {"x": 0, "y": 0, "z": 0})
            if not isinstance(origin, dict) or set(origin) - {"x", "y", "z"}:
                return None, None, f"Operand {index}: invalid origin"
            if any(
                not isinstance(v, (int, float))
                or isinstance(v, bool)
                or not math.isfinite(v)
                for v in origin.values()
            ):
                return None, None, f"Operand {index}: origin must be finite numbers"
            try:
                item = PrimitiveGeometry.model_validate(
                    {
                        "source": "primitive",
                        "primitive": primitive,
                        "parameters": checked,
                        "origin": origin,
                    }
                )
            except (ValidationError, ValueError) as exc:
                return None, None, str(exc)
            normalized.append(item.model_dump(mode="json"))

        if len(dims) != 1 or 1 in dims:
            return None, None, "Boolean operands must share a 2D or 3D dimension"
        dimension = next(iter(dims))
        try:
            spec = GeometrySpec.model_validate(
                {
                    "name": name,
                    "units": units,
                    "definition": {
                        "source": "csg",
                        "operation": operation,
                        "operands": normalized,
                    },
                }
            )
        except (ValidationError, ValueError) as exc:
            return None, None, str(exc)
        return spec, dimension, None

    def create_boolean_geometry(
        self,
        name: str,
        operation: Literal["cut", "fuse", "intersect"],
        operands: list[dict[str, Any]],
        units: LengthUnitName = "mm",
    ) -> str:
        """Create a CAD boolean geometry from inline primitive operands.

        Args:
            name: Geometry name.
            operation: Cut (first minus rest), fuse, or intersect.
            operands: At least two objects with primitive, parameters,
                and optional origin {x, y, z}. Concentric annulus example:
                [{"primitive":"disk","parameters":{"radius":2}},
                 {"primitive":"disk","parameters":{"radius":1}}].
            units: Length units for every operand.
        """
        spec, dimension, error = self._build_csg_spec(
            name,
            operation,
            operands,
            units,
        )
        if error or spec is None:
            return self._error(error or "Invalid CSG geometry")
        result = self.geometry.create_geometry(spec.model_dump(mode="json"))
        if result.get("ok") and result.get("job_id"):
            self.submitted_job_ids.append(result["job_id"])
        return json.dumps({**result, "dimension": dimension})

    def create_boolean_geometry_and_mesh(
        self,
        name: str,
        operation: Literal["cut", "fuse", "intersect"],
        operands: list[dict[str, Any]],
        units: LengthUnitName = "mm",
        dimension: Literal[2, 3] | None = None,
        min_size: float = 1.0,
        max_size: float = 5.0,
        element_family: ElementFamilyName | None = None,
    ) -> str:
        """Atomically queue CAD boolean geometry and dependent mesh jobs.

        Args:
            name: Shape name.
            operation: Cut (first minus rest), fuse, or intersect.
            operands: Inline primitive definitions, optionally with origins.
                For an annulus, cut a smaller disk from a larger disk.
            units: Geometry length units.
            dimension: Inferred from operands if omitted, 2 or 3.
            min_size: Minimum mesh element size.
            max_size: Maximum mesh element size.
            element_family: 2D triangular/quadrilateral or 3D tetrahedral.
        """
        spec, actual_dimension, error = self._build_csg_spec(
            name,
            operation,
            operands,
            units,
        )
        if error or spec is None or actual_dimension is None:
            return self._error(error or "Invalid CSG geometry")
        if dimension is not None and dimension != actual_dimension:
            return self._error(
                f"Boolean geometry is {actual_dimension}D, not {dimension}D"
            )
        settings, error = self._validate_mesh_settings(
            actual_dimension,
            min_size,
            max_size,
            element_family,
        )
        if error or settings is None:
            return self._error(error or "Invalid mesh settings")
        geometry_job, mesh_job = self.geometry.job_manager.submit_geometry_mesh(
            project_id=self.geometry.project_id,
            geometry_payload=spec.model_dump(mode="json"),
            mesh_settings=settings.model_dump(mode="json"),
        )
        self.submitted_job_ids.extend([str(geometry_job.id), str(mesh_job.id)])
        return json.dumps(
            {
                "ok": True,
                "message": "CAD boolean geometry and mesh workflow submitted",
                "status": "queued",
                "dimension": actual_dimension,
                "element_family": settings.element_family.value,
                "geometry_job_id": str(geometry_job.id),
                "mesh_job_id": str(mesh_job.id),
                "workflow": [
                    {"job_id": str(geometry_job.id), "type": geometry_job.type.value},
                    {
                        "job_id": str(mesh_job.id),
                        "type": mesh_job.type.value,
                        "depends_on": str(geometry_job.id),
                    },
                ],
            }
        )

    def get_job_status(self, job_id: str) -> str:
        """Inspect an existing simulation job.

        Args:
            job_id: Job ID to inspect.
        """
        return json.dumps(self.geometry.get_job_status(job_id))
