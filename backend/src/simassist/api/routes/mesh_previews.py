from __future__ import annotations

from collections import Counter
from pathlib import Path
from uuid import UUID

import meshio
import numpy as np
from fastapi import APIRouter, HTTPException

from simassist.api.dependencies import ArtifactStoreDep, JobManagerDep
from simassist.core.models.artifact import ArtifactType
from simassist.jobs.models import JobStatus, JobType

router = APIRouter(prefix="/api/projects/{project_id}", tags=["Mesh previews"])

MAX_SURFACE_TRIANGLES = 300_000


def build_tetra_surface_preview(mesh_path: Path) -> dict:
    """Convert tetrahedral Gmsh volume mesh to its exterior triangle surface.

    Shared faces are removed; original mesh is never modified.
    Higher-order tetrahedra are displayed by their four corner nodes.
    """
    mesh = meshio.read(mesh_path)
    points = mesh.points
    if len(points) == 0:
        raise ValueError("Mesh has no nodes")

    faces: Counter[tuple[int, int, int]] = Counter()
    orientations: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    volume_elements = 0

    for block in mesh.cells:
        if not block.type.startswith("tetra"):
            continue
        for cell in block.data:
            if len(cell) < 4:
                raise ValueError("Invalid tetrahedral element")
            a, b, c, d = (int(v) for v in cell[:4])
            if len({a, b, c, d}) != 4:
                raise ValueError("Degenerate tetrahedral element")
            volume_elements += 1
            for face, opposite in (
                ((a, b, c), d),
                ((a, d, b), c),
                ((a, c, d), b),
                ((b, d, c), a),
            ):
                key = tuple(sorted(face))
                faces[key] += 1
                # Orient outward using the opposite corner, independent of
                # tetrahedron ordering in the original mesh.
                p0, p1, p2 = (points[i] for i in face)
                toward = points[opposite] - p0
                normal = np.cross(p1 - p0, p2 - p0)
                oriented = (
                    face if normal.dot(toward) < 0 else (face[0], face[2], face[1])
                )
                orientations[key] = oriented

    if volume_elements == 0:
        raise ValueError("Mesh contains no tetrahedral volume elements")
    if any(count > 2 for count in faces.values()):
        raise ValueError(
            "Non-manifold tetrahedral mesh: face shared by more than two elements"
        )

    boundary = [orientations[key] for key, count in faces.items() if count == 1]
    if not boundary:
        raise ValueError("Mesh has no exterior surface")
    if len(boundary) > MAX_SURFACE_TRIANGLES:
        raise OverflowError("Mesh preview too large; reduce mesh density")

    used = sorted({index for triangle in boundary for index in triangle})
    compact = {old: new for new, old in enumerate(used)}
    return {
        "points": [[float(v) for v in points[index][:3]] for index in used],
        "triangles": [[compact[v] for v in triangle] for triangle in boundary],
        "point_count": len(used),
        "triangle_count": len(boundary),
        "volume_element_count": volume_elements,
        "source_node_count": len(points),
    }


def build_mesh_preview(mesh_path: Path) -> dict:
    """Read the actual 1D, 2D or 3D mesh and emit VTK-friendly cells.

    Preserve quadrilateral faces (no artificial diagonal in the viewer).
    Extract only external tetra faces for 3D.
    """
    mesh = meshio.read(mesh_path)
    points = mesh.points
    if len(points) == 0:
        raise ValueError("Mesh has no nodes")
    dim = 0
    for block in mesh.cells:
        kind = block.type.lower()
        if kind.startswith("tetra"):
            dim = max(dim, 3)
        elif kind.startswith(("triangle", "quad")):
            dim = max(dim, 2)
        elif kind.startswith("line"):
            dim = max(dim, 1)
    if dim == 0:
        raise ValueError("No supported 1D, 2D or 3D mesh cells")
    if dim == 3:
        result = build_tetra_surface_preview(mesh_path)
        return {
            **result,
            "dimension": 3,
            "lines": [],
            "quads": [],
            "line_count": 0,
            "quad_count": 0,
            "triangle_count": result["triangle_count"],
        }

    lines: list[list[int]] = []
    triangles: list[list[int]] = []
    quads: list[list[int]] = []
    for block in mesh.cells:
        kind = block.type.lower()
        if dim == 1 and kind.startswith("line"):
            lines.extend([[int(v) for v in cell[:2]] for cell in block.data])
        elif dim == 2 and kind.startswith("triangle"):
            triangles.extend([[int(v) for v in cell[:3]] for cell in block.data])
        elif dim == 2 and kind.startswith("quad"):
            quads.extend([[int(v) for v in cell[:4]] for cell in block.data])
    if dim == 1 and not lines:
        raise ValueError("No line elements in 1D mesh")
    if dim == 2 and not (triangles or quads):
        raise ValueError("No surface elements in 2D mesh")
    count = len(lines) + len(triangles) + len(quads)
    if count > MAX_SURFACE_TRIANGLES:
        raise OverflowError("Mesh preview too large; reduce mesh density")
    used = sorted({v for cell in (*lines, *triangles, *quads) for v in cell})
    compact = {old: new for new, old in enumerate(used)}
    return {
        "dimension": dim,
        "points": [[float(v) for v in points[index][:3]] for index in used],
        "lines": [[compact[v] for v in line] for line in lines],
        "triangles": [[compact[v] for v in tri] for tri in triangles],
        "quads": [[compact[v] for v in quad] for quad in quads],
        "point_count": len(used),
        "line_count": len(lines),
        "triangle_count": len(triangles),
        "quad_count": len(quads),
        "volume_element_count": 0,
        "source_node_count": len(points),
    }


@router.get("/geometries/{geometry_job_id}/mesh-preview")
def get_latest_mesh_preview(
    project_id: UUID,
    geometry_job_id: UUID,
    manager: JobManagerDep,
    store: ArtifactStoreDep,
):
    try:
        geometry = manager.get(geometry_job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Geometry not found") from exc

    if (
        geometry.project_id != project_id
        or geometry.type != JobType.GEOMETRY_CREATE
        or geometry.status != JobStatus.COMPLETED
    ):
        raise HTTPException(status_code=404, detail="Completed geometry not found")

    geometry_artifact_id = str((geometry.result or {}).get("artifact_id", ""))
    if not geometry_artifact_id:
        raise HTTPException(status_code=404, detail="Geometry has no STEP artifact")

    # list_by_project is newest-first. Match by saved geometry artifact,
    # not by mesh title or the currently selected frontend view.
    match = None
    for job in manager.list_by_project(project_id):
        if job.type != JobType.MESH_GENERATE or job.status != JobStatus.COMPLETED:
            continue
        result = job.result or {}
        payload = job.input or {}
        if (
            str(result.get("geometry_artifact_id", "")) == geometry_artifact_id
            or str(payload.get("geometry_artifact_id", "")) == geometry_artifact_id
            or str(payload.get("geometry_job_id", "")) == str(geometry_job_id)
        ):
            match = job
            break

    if match is None:
        raise HTTPException(
            status_code=404, detail="No completed mesh exists for this geometry"
        )

    mesh_id = (match.result or {}).get("artifact_id")
    if not mesh_id:
        raise HTTPException(status_code=404, detail="Mesh job has no artifact")
    try:
        artifact_id = UUID(str(mesh_id))
        artifact = store.get(artifact_id)
        if (
            artifact.project_id != project_id
            or artifact.type != ArtifactType.MESH
            or UUID(geometry_artifact_id) not in artifact.parent_ids
        ):
            raise HTTPException(
                status_code=404, detail="Mesh artifact not found for geometry"
            )
        path = store.resolve_path(artifact_id)
        if path.suffix.lower() != ".msh":
            raise HTTPException(status_code=422, detail="Expected Gmsh .msh artifact")
        preview = build_mesh_preview(path)
    except (KeyError, FileNotFoundError) as exc:
        raise HTTPException(
            status_code=404, detail="Mesh artifact file missing"
        ) from exc
    except OverflowError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=422, detail=f"Mesh preview failed: {exc}"
        ) from exc

    return {
        **preview,
        "mesh_job_id": str(match.id),
        "mesh_artifact_id": str(artifact_id),
    }
