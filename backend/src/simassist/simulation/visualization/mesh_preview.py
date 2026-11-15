"""Indexed external-boundary previews. Volumetric .msh artifacts stay untouched."""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

import meshio
import numpy as np

MAX_SURFACE_TRIANGLES = 300_000
PREVIEW_VERSION = 2


def _validate_points(mesh):
    points = np.asarray(mesh.points, dtype=np.float64)
    if not len(points):
        raise ValueError("Mesh has no nodes")
    if points.ndim != 2 or points.shape[1] < 3 or not np.isfinite(points[:, :3]).all():
        raise ValueError("Mesh coordinates must be finite Nx3 points")
    return points[:, :3]


def _indices(blocks, width, node_count):
    if not blocks:
        return np.empty((0, width), dtype=np.int64)
    if any(block.ndim != 2 or block.shape[1] < width for block in blocks):
        raise ValueError("Invalid mesh element connectivity")
    cells = np.concatenate([block[:, :width] for block in blocks]).astype(
        np.int64, copy=False
    )
    if len(cells) and (cells.min() < 0 or cells.max() >= node_count):
        raise ValueError("Mesh references an invalid node")
    if len(cells) and np.any(np.diff(np.sort(cells, axis=1), axis=1) == 0):
        raise ValueError("Degenerate mesh element with repeated corner nodes")
    return cells


def _tetra_boundary(mesh, points):
    cells = _indices(
        [b.data for b in mesh.cells if b.type.startswith("tetra")], 4, len(points)
    )
    if not len(cells):
        raise ValueError("Mesh contains no tetrahedral volume elements")
    # Group every face by its sorted corner IDs. Only multiplicity-one faces
    # are exterior; compute outward normals for those faces, not all 4*N faces.
    faces = cells[:, [[0, 1, 2], [0, 3, 1], [0, 2, 3], [1, 3, 2]]].reshape(-1, 3)
    keys = np.sort(faces, axis=1)
    _, first, counts = np.unique(keys, axis=0, return_index=True, return_counts=True)
    if np.any(counts > 2):
        raise ValueError(
            "Non-manifold tetrahedral mesh: face shared by more than two elements"
        )
    exterior = first[counts == 1]
    if not len(exterior):
        raise ValueError("Mesh has no exterior surface")
    if len(exterior) > MAX_SURFACE_TRIANGLES:
        raise OverflowError("Mesh preview too large; reduce mesh density")
    triangles = faces[exterior].copy()
    opposite = cells[exterior // 4, np.array([3, 2, 1, 0])[exterior % 4]]
    vertices = points[triangles]
    normal = np.cross(vertices[:, 1] - vertices[:, 0], vertices[:, 2] - vertices[:, 0])
    flip = np.einsum("ij,ij->i", normal, points[opposite] - vertices[:, 0]) >= 0
    triangles[flip] = triangles[flip][:, [0, 2, 1]]
    return triangles, len(cells)


def preview_from_mesh(mesh, tetra_only=False):
    points = _validate_points(mesh)
    dimension = max(
        (
            3
            if b.type.startswith("tetra")
            else 2
            if b.type.startswith(("triangle", "quad"))
            else 1
            if b.type.startswith("line")
            else 0
            for b in mesh.cells
            if len(b.data)
        ),
        default=0,
    )
    triangles = np.empty((0, 3), dtype=np.int64)
    quads = np.empty((0, 4), dtype=np.int64)
    lines = np.empty((0, 2), dtype=np.int64)
    volume_elements = 0
    if tetra_only or dimension == 3:
        triangles, volume_elements = _tetra_boundary(mesh, points)
        dimension = 3
    elif dimension == 2:
        triangles = _indices(
            [b.data for b in mesh.cells if b.type.startswith("triangle")],
            3,
            len(points),
        )
        quads = _indices(
            [b.data for b in mesh.cells if b.type.startswith("quad")], 4, len(points)
        )
    elif dimension == 1:
        lines = _indices(
            [b.data for b in mesh.cells if b.type.startswith("line")], 2, len(points)
        )
    else:
        raise ValueError("No supported 1D, 2D or 3D mesh cells")
    if len(triangles) + len(quads) + len(lines) > MAX_SURFACE_TRIANGLES:
        raise OverflowError("Mesh preview too large; reduce mesh density")
    used, inverse = np.unique(
        np.concatenate([triangles.ravel(), quads.ravel(), lines.ravel()]),
        return_inverse=True,
    )
    ti, qi = triangles.size, triangles.size + quads.size
    return {
        "format_version": PREVIEW_VERSION,
        "dimension": dimension,
        "points": points[used].tolist(),
        "triangles": inverse[:ti].reshape(-1, 3).tolist(),
        "quads": inverse[ti:qi].reshape(-1, 4).tolist(),
        "lines": inverse[qi:].reshape(-1, 2).tolist(),
        "point_count": len(used),
        "triangle_count": len(triangles),
        "quad_count": len(quads),
        "line_count": len(lines),
        "volume_element_count": volume_elements,
        "source_node_count": len(points),
    }


def build_mesh_preview(mesh_path: Path, timings=None, tetra_only=False):
    started = perf_counter()
    mesh = meshio.read(mesh_path)
    parsed = perf_counter()
    result = preview_from_mesh(mesh, tetra_only=tetra_only)
    if timings is not None:
        timings.update(
            parse_ms=(parsed - started) * 1000,
            extraction_ms=(perf_counter() - parsed) * 1000,
        )
    return result


def build_tetra_surface_preview(mesh_path: Path):
    return build_mesh_preview(mesh_path, tetra_only=True)
