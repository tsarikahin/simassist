from __future__ import annotations

import json
import math
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from simassist.agents.tools.geometry import GeometryTools
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshRequest, MeshSettings
from simassist.jobs.models import JobType


class SimulationTools:
    """Agent-facing tools for engineering simulations."""

    def __init__(self, geometry: GeometryTools):
        self.geometry = geometry
        self.submitted_job_ids: list[str] = []

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
                    "box": {
                        "dx": "length",
                        "dy": "width",
                        "dz": "height",
                    }
                },
                "units": ["mm", "cm", "m", "in"],
                "constraints": (
                    "All dimensions must be positive. "
                    "Only primitive creation is implemented."
                ),
            }
        )

    def create_geometry(
        self,
        name: str,
        primitive: Literal["box", "cylinder", "sphere"],
        parameters: dict[str, float],
        units: Literal["mm", "cm", "m", "in"] = "mm",
    ) -> str:
        """Submit a geometry creation job.

        Args:
            name: Descriptive name for the geometry.
            primitive: Geometry primitive to create.
            parameters: Dimensions of the primitive.
                Box: length, width, height.
                Cylinder: radius, height.
                Sphere: radius.
            units: Length units.
        """
        required = {
            "box": {"length", "width", "height"},
            "cylinder": {"radius", "height"},
            "sphere": {"radius"},
        }

        normalized = dict(parameters)

        if primitive == "box":
            aliases = {
                "dx": "length",
                "dy": "width",
                "dz": "height",
            }

            for alias, canonical in aliases.items():
                if alias in normalized:
                    if canonical in normalized:
                        return json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    f"Conflicting parameters: {alias} and {canonical}"
                                ),
                            }
                        )

                    normalized[canonical] = normalized.pop(alias)

        if set(normalized) != required[primitive]:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"{primitive} requires parameters {sorted(required[primitive])}"
                    ),
                }
            )

        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in normalized.values()
        ):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Dimensions must be positive finite numbers",
                }
            )

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
    ) -> str:
        """Submit a mesh job for a completed geometry job.

        Args:
            geometry_job_id: ID returned by create_geometry.
            dimension: Mesh dimension, 2 or 3.
            min_size: Minimum element size, in geometry units.
            max_size: Maximum element size, in geometry units.
        """
        try:
            UUID(geometry_job_id)
        except (ValueError, TypeError):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Invalid geometry job ID",
                }
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
            return json.dumps(
                {
                    "ok": False,
                    "error": "Invalid mesh element size settings",
                }
            )

        geometry_status = self.geometry.get_job_status(geometry_job_id)

        if not geometry_status.get("ok"):
            return json.dumps(geometry_status)

        if geometry_status.get("job_type") != JobType.GEOMETRY_CREATE:
            return json.dumps(
                {
                    "ok": False,
                    "error": "The provided job is not a geometry job",
                }
            )

        if geometry_status.get("status") != "completed":
            return json.dumps(
                {
                    "ok": False,
                    "error": "Geometry job is not completed yet",
                    "status": geometry_status.get("status"),
                    "geometry_job_id": geometry_job_id,
                }
            )

        geometry_result = geometry_status.get("result") or {}
        artifact_id = geometry_result.get("artifact_id")

        if not artifact_id:
            return json.dumps(
                {
                    "ok": False,
                    "error": "Geometry job has no artifact ID",
                }
            )

        try:
            request = MeshRequest(
                geometry_artifact_id=UUID(str(artifact_id)),
                settings=MeshSettings(
                    dimension=dimension,
                    min_size=min_size,
                    max_size=max_size,
                ),
            )

            job = self.geometry.job_manager.submit(
                project_id=self.geometry.project_id,
                job_type=JobType.MESH_GENERATE,
                payload=request.model_dump(mode="json"),
            )
        except (ValueError, TypeError) as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                }
            )

        self.submitted_job_ids.append(str(job.id))

        return json.dumps(
            {
                "ok": True,
                "job_id": str(job.id),
                "job_type": job.type.value,
                "status": job.status.value,
                "geometry_artifact_id": str(request.geometry_artifact_id),
                "message": "Mesh generation job submitted",
            }
        )

    def create_geometry_and_mesh(
        self,
        name: str,
        primitive: Literal["box", "cylinder", "sphere"],
        parameters: dict[str, float],
        units: Literal["mm", "cm", "m", "in"] = "mm",
        dimension: Literal[2, 3] = 3,
        min_size: float = 1.0,
        max_size: float = 5.0,
    ) -> str:
        """Create a geometry and automatically mesh it.

        Submit a dependent two-step workflow. The backend waits
        for geometry completion and resolves the geometry artifact.

        Args:
            name: Name of the geometry.
            primitive: box, cylinder, or sphere.
            parameters: Box uses length/width/height;
                cylinder uses radius/height; sphere uses radius.
            units: Geometry length units.
            dimension: Mesh dimension, 2 or 3.
            min_size: Minimum mesh size in geometry units.
            max_size: Maximum mesh size in geometry units.
        """
        required = {
            "box": {"length", "width", "height"},
            "cylinder": {"radius", "height"},
            "sphere": {"radius"},
        }

        normalized = dict(parameters)

        if primitive == "box":
            aliases = {
                "dx": "length",
                "dy": "width",
                "dz": "height",
            }

            for alias, canonical in aliases.items():
                if alias in normalized:
                    if canonical in normalized:
                        return json.dumps(
                            {
                                "ok": False,
                                "error": (
                                    f"Conflicting parameters: {alias} and {canonical}"
                                ),
                            }
                        )

                    normalized[canonical] = normalized.pop(alias)

        if set(normalized) != required[primitive]:
            return json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"{primitive} requires parameters {sorted(required[primitive])}"
                    ),
                }
            )

        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value <= 0
            for value in normalized.values()
        ):
            return json.dumps(
                {
                    "ok": False,
                    "error": "Dimensions must be positive finite numbers",
                }
            )

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

            mesh_settings = MeshSettings(
                dimension=dimension,
                min_size=min_size,
                max_size=max_size,
            )

        except (ValidationError, ValueError) as exc:
            return json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                }
            )

        geometry_job, mesh_job = self.geometry.job_manager.submit_geometry_mesh(
            project_id=self.geometry.project_id,
            geometry_payload=geometry_spec.model_dump(mode="json"),
            mesh_settings=mesh_settings.model_dump(mode="json"),
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
                "message": "Geometry and mesh workflow submitted",
                "geometry_job_id": str(geometry_job.id),
                "mesh_job_id": str(mesh_job.id),
                "status": "queued",
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
        """Get the current status of a simulation job.

        Args:
            job_id: ID of the job to inspect.
        """
        return json.dumps(self.geometry.get_job_status(job_id))
