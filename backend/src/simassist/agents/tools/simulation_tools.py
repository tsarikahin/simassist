from __future__ import annotations

import json
import math
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from simassist.agents.tools.geometry import GeometryTools
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import (
    MeshRequest,
    MeshSettings,
)
from simassist.jobs.models import JobType

PrimitiveName = Literal["box", "cylinder", "sphere"]
LengthUnitName = Literal["mm", "cm", "m", "in"]
ElementFamilyName = Literal["tetrahedral", "hexahedral"]

GEOMETRY_PARAMETERS: dict[str, set[str]] = {
    "box": {"length", "width", "height"},
    "cylinder": {"radius", "height"},
    "sphere": {"radius"},
}

BOX_ALIASES = {
    "dx": "length",
    "dy": "width",
    "dz": "height",
}


class SimulationTools:
    """Agent-facing tools for engineering simulations."""

    def __init__(self, geometry: GeometryTools):
        self.geometry = geometry
        self.submitted_job_ids: list[str] = []

    @staticmethod
    def _error(message: str, **details: object) -> str:
        return json.dumps(
            {
                "ok": False,
                "error": message,
                **details,
            }
        )

    @staticmethod
    def _validate_element_family(
        element_family: str,
        dimension: int,
    ) -> str | None:
        if element_family == "hexahedral":
            return (
                "Hexahedral meshing is not supported by the "
                "current Gmsh engine. No job was submitted. "
                "Ask the user before switching to tetrahedral."
            )

        if element_family != "tetrahedral":
            return f"Unsupported element family: {element_family}"

        if dimension not in (2, 3):
            return "Mesh dimension must be 2 or 3"

        return None

    @staticmethod
    def _normalize_parameters(
        primitive: str,
        parameters: dict[str, float],
    ) -> tuple[dict[str, float] | None, str | None]:
        required = GEOMETRY_PARAMETERS.get(primitive)

        if required is None:
            return None, f"Unsupported primitive: {primitive}"

        normalized = dict(parameters)

        if primitive == "box":
            for alias, canonical in BOX_ALIASES.items():
                if alias in normalized:
                    if canonical in normalized:
                        return (
                            None,
                            f"Conflicting parameters: {alias} and {canonical}",
                        )

                    normalized[canonical] = normalized.pop(alias)

        if set(normalized) != required:
            return (
                None,
                f"{primitive} requires parameters {sorted(required)}",
            )

        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in normalized.values()
        ):
            return (
                None,
                "Dimensions must be positive finite numbers",
            )

        return normalized, None

    @staticmethod
    def _validate_mesh_settings(
        dimension: int,
        min_size: float,
        max_size: float,
        element_family: str,
    ) -> tuple[MeshSettings | None, str | None]:
        family_error = SimulationTools._validate_element_family(
            element_family,
            dimension,
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
        """List supported geometry primitives and parameters."""
        return json.dumps(
            {
                "supported": {
                    "box": ["length", "width", "height"],
                    "cylinder": ["radius", "height"],
                    "sphere": ["radius"],
                },
                "aliases": {
                    "box": BOX_ALIASES,
                },
                "units": ["mm", "cm", "m", "in"],
                "constraints": (
                    "All dimensions must be positive. "
                    "Only primitive creation is implemented."
                ),
                "meshing": {
                    "engine": "gmsh",
                    "supported_3d_element_families": ["tetrahedral"],
                    "unsupported_3d_element_families": ["hexahedral"],
                    "supported_2d_elements": ["triangle"],
                },
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
            parameters: Box uses length/width/height.
                Cylinder uses radius/height.
                Sphere uses radius.
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
        geometry_job_id: str,
        dimension: Literal[2, 3] = 3,
        min_size: float = 1.0,
        max_size: float = 5.0,
        element_family: ElementFamilyName = "tetrahedral",
    ) -> str:
        """Mesh an existing completed geometry.

        Args:
            geometry_job_id: Existing completed geometry job ID.
            dimension: 2D surface mesh or 3D volume mesh.
            min_size: Minimum mesh size in geometry units.
            max_size: Maximum mesh size in geometry units.
            element_family: Requested volume element family.
                Tetrahedral is supported for 3D.
                Hexahedral is NOT supported and is rejected.
                Never silently substitute tetrahedral for hex.
        """
        settings, error = self._validate_mesh_settings(
            dimension,
            min_size,
            max_size,
            element_family,
        )

        if error or settings is None:
            return self._error(
                error or "Invalid mesh settings",
                requested_element_family=element_family,
                supported_element_families=["tetrahedral"],
            )

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
        dimension: Literal[2, 3] = 3,
        min_size: float = 1.0,
        max_size: float = 5.0,
        element_family: ElementFamilyName = "tetrahedral",
    ) -> str:
        """Submit an automatic geometry-to-mesh workflow.

        Args:
            name: Geometry name.
            primitive: Box, cylinder, or sphere.
            parameters: Primitive dimensions.
            units: Geometry length unit.
            dimension: 2D or 3D mesh dimension.
            min_size: Minimum mesh size.
            max_size: Maximum mesh size.
            element_family: Requested 3D volume element family.
                Tetrahedral is supported by Gmsh.
                Hexahedral is unsupported; reject without
                submitting any geometry or mesh jobs.
        """
        settings, settings_error = self._validate_mesh_settings(
            dimension,
            min_size,
            max_size,
            element_family,
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

        self.submitted_job_ids.extend(
            [
                str(geometry_job.id),
                str(mesh_job.id),
            ]
        )

        return json.dumps(
            {
                "ok": True,
                "message": ("Geometry and mesh workflow submitted"),
                "geometry_job_id": str(geometry_job.id),
                "mesh_job_id": str(mesh_job.id),
                "status": "queued",
                "element_family": settings.element_family.value,
                "workflow": [
                    {
                        "job_id": str(geometry_job.id),
                        "type": geometry_job.type.value,
                    },
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
