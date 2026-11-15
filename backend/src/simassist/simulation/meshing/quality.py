"""Dimension-aware *geometric* mesh diagnostics; not a solver-quality certificate.

Quality convention: 0 = degenerate, 1 = ideal element. The definitions
are explicitly listed in the JSON report. Only linear corner nodes are used
for higher order elements; curved midside geometry is not evaluated.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

MAX_ANALYSIS_ELEMENTS = 250_000
LOW_QUALITY_THRESHOLD = 0.2
EPS = 1.0e-12
CELL_FAMILIES: dict[str, tuple[int, int, str]] = {
    "line": (1, 2, "line"),
    "triangle": (2, 3, "triangle"),
    "quad": (2, 4, "quadrilateral"),
    "tetra": (3, 4, "tetrahedral"),
}
EDGES_TETRA = ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))


def _family(kind: str) -> tuple[int, int, str] | None:
    for prefix, value in CELL_FAMILIES.items():
        if kind.lower().startswith(prefix):
            return value
    return None


def _norm(vector: np.ndarray) -> float:
    return float(np.linalg.norm(vector))


def _element_metrics(
    vertices: np.ndarray, family: str
) -> tuple[float | None, float, float]:
    """Return quality, max/min corner-edge aspect, and length (only for lines)."""
    if family == "line":
        length = _norm(vertices[1] - vertices[0])
        return None, 1.0, length

    if family == "triangle":
        edges = [
            _norm(vertices[1] - vertices[0]),
            _norm(vertices[2] - vertices[1]),
            _norm(vertices[0] - vertices[2]),
        ]
        area = _norm(np.cross(vertices[1] - vertices[0], vertices[2] - vertices[0])) / 2
        denom = sum(edge * edge for edge in edges)
        score = 4 * math.sqrt(3) * area / denom if denom > EPS else 0.0
    elif family == "quadrilateral":
        edges = [_norm(vertices[(i + 1) % 4] - vertices[i]) for i in range(4)]
        corners = []
        for i in range(4):
            previous = vertices[(i - 1) % 4] - vertices[i]
            following = vertices[(i + 1) % 4] - vertices[i]
            denom = _norm(previous) * _norm(following)
            corners.append(
                _norm(np.cross(previous, following)) / denom if denom > EPS else 0
            )
        # Penalizes skew and stretched side lengths; does not detect warped faces.
        score = min(corners) * min(edges) / max(edges) if max(edges) > EPS else 0.0
    elif family == "tetrahedral":
        edges = [_norm(vertices[j] - vertices[i]) for i, j in EDGES_TETRA]
        volume6 = abs(
            float(
                np.dot(
                    vertices[1] - vertices[0],
                    np.cross(vertices[2] - vertices[0], vertices[3] - vertices[0]),
                )
            )
        )
        denom = sum(edge * edge for edge in edges)
        score = 12 * ((volume6 / 2) ** (2 / 3)) / denom if denom > EPS else 0.0
    else:
        raise ValueError(f"Unsupported cell family: {family}")

    aspect = max(edges) / min(edges) if min(edges) > EPS else float("inf")
    return max(0.0, min(1.0, score)), aspect, 0.0


def analyze_mesh(mesh: Any) -> dict[str, Any]:
    """Analyze meshio-compatible mesh; ignore lower-dimensional boundary cells."""
    points = np.asarray(mesh.points, dtype=float)
    if points.ndim != 2 or points.shape[1] < 3 or not np.isfinite(points).all():
        raise ValueError("Mesh coordinates must be finite Nx3 points")
    if not len(points):
        raise ValueError("Mesh has no points")

    blocks = []
    dimension = 0
    for block in mesh.cells:
        info = _family(block.type)
        if info and len(block.data):
            dimension = max(dimension, info[0])
            blocks.append((block, info))
    if dimension == 0:
        raise ValueError("No supported line, triangle, quad or tetrahedral cells")

    selected = [(block, info) for block, info in blocks if info[0] == dimension]
    count = sum(len(block.data) for block, _ in selected)
    if count > MAX_ANALYSIS_ELEMENTS:
        raise OverflowError(
            f"Mesh quality analysis limited to {MAX_ANALYSIS_ELEMENTS} elements"
        )

    families: dict[str, int] = {}
    qualities: list[float] = []
    aspects: list[float] = []
    lengths: list[float] = []
    bad: list[dict[str, Any]] = []
    degenerate_count = 0
    low_count = 0
    element_id = 0

    for block, (_, corners, family) in selected:
        families[family] = families.get(family, 0) + len(block.data)
        for cell in block.data:
            indices = np.asarray(cell[:corners], dtype=int)
            if (
                len(indices) != corners
                or (indices < 0).any()
                or (indices >= len(points)).any()
            ):
                raise ValueError("Invalid mesh cell connectivity")
            if len(set(indices.tolist())) != corners:
                score, aspect, length = (
                    (0.0 if dimension > 1 else None),
                    float("inf"),
                    0.0,
                )
            else:
                score, aspect, length = _element_metrics(points[indices, :3], family)
            if not math.isfinite(aspect):
                aspect = None
            if dimension == 1:
                lengths.append(length)
                is_bad = length <= EPS
            else:
                assert score is not None
                qualities.append(score)
                if aspect is not None:
                    aspects.append(aspect)
                is_bad = score < LOW_QUALITY_THRESHOLD
            if is_bad:
                low_count += 1
            if length <= EPS if dimension == 1 else score <= EPS:
                degenerate_count += 1
            if is_bad or dimension != 1:
                bad.append(
                    {
                        "index": element_id,
                        "family": family,
                        "quality": round(score, 6) if score is not None else None,
                        "edge_aspect_ratio": round(aspect, 4)
                        if aspect is not None
                        else None,
                        "length": round(length, 6) if dimension == 1 else None,
                    }
                )
            element_id += 1

    worst = sorted(
        bad,
        key=lambda entry: (
            entry["quality"] if entry["quality"] is not None else entry["length"]
        ),
    )[:10]

    def stats(values: list[float]) -> dict[str, float] | None:
        return (
            {
                "min": round(min(values), 6),
                "mean": round(sum(values) / len(values), 6),
                "max": round(max(values), 6),
            }
            if values
            else None
        )

    methods = {
        1: "segment length (geometry units); no shape score for 1D",
        2: "triangle: mean ratio; quad: minimum corner sine times shortest/longest edge",
        3: "tetrahedron: mean-ratio quality using linear corner nodes",
    }
    return {
        "dimension": dimension,
        "node_count": len(points),
        "analyzed_element_count": count,
        "element_families": families,
        "quality_method": methods[dimension],
        "quality_range": "0 degenerate to 1 ideal (2D/3D only)",
        "low_quality_threshold": LOW_QUALITY_THRESHOLD if dimension > 1 else None,
        "low_quality_count": low_count,
        "degenerate_count": degenerate_count,
        "quality": stats(qualities),
        "edge_aspect_ratio": stats(aspects),
        "segment_length": stats(lengths),
        "worst_elements": worst,
        "limitations": (
            "Geometric diagnostic, not simulation convergence or Jacobian certification. "
            "Only corner nodes assessed for high-order elements; element IDs are "
            "analysis-local indices, not Gmsh element tags."
        ),
    }


def analyze_mesh_file(mesh_path: Path) -> dict[str, Any]:
    import meshio

    return analyze_mesh(meshio.read(mesh_path))
