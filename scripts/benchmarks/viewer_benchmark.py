"""Reproducible 120k-tet stage benchmark; derived files stay under .benchmarks."""

from __future__ import annotations

import argparse
import json
import platform
import runpy
from pathlib import Path
from time import perf_counter
from unittest.mock import patch
from uuid import uuid4

import meshio
import numpy as np

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, default=Path(".benchmarks/viewer-1118a"))
parser.add_argument("--legacy-source", type=Path)
parser.add_argument("--generate-only", action="store_true")
args = parser.parse_args()
root = args.root.resolve()
root.mkdir(parents=True, exist_ok=True)
mesh_path = root / "120k-tetra.msh"
if not mesh_path.exists():
    nx, ny, nz = 20, 20, 50
    x, y, z = np.meshgrid(
        np.arange(nx + 1), np.arange(ny + 1), np.arange(nz + 1), indexing="ij"
    )
    points = np.column_stack((x.ravel(), y.ravel(), z.ravel())).astype(float)
    i, j, k = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz), indexing="ij")
    a = ((i * (ny + 1) + j) * (nz + 1) + k).ravel()
    b = a + (ny + 1) * (nz + 1)
    c = b + (nz + 1)
    d = a + (nz + 1)
    e = a + 1
    f = b + 1
    g = c + 1
    h = d + 1
    cells = np.stack(
        [
            np.column_stack(t)
            for t in [
                (a, b, c, g),
                (a, c, d, g),
                (a, d, h, g),
                (a, h, e, g),
                (a, e, f, g),
                (a, f, b, g),
            ]
        ]
    ).reshape(-1, 4)
    meshio.write(
        mesh_path,
        meshio.Mesh(points, cells=[("tetra", cells)]),
        file_format="gmsh22",
        binary=True,
    )
if args.generate_only:
    print(mesh_path)
    raise SystemExit(0)
report = {
    "platform": platform.platform(),
    "processor": platform.processor(),
    "python": platform.python_version(),
    "numpy": np.__version__,
    "meshio": meshio.__version__,
    "source_bytes": mesh_path.stat().st_size,
    "loads": [],
}
if args.legacy_source:
    namespace = runpy.run_path(str(args.legacy_source))
    original_read = meshio.read
    for name in ["first", "repeat"]:
        reads = []

        def timed_read(*read_args, _samples=reads, **kwargs):
            started = perf_counter()
            value = original_read(*read_args, **kwargs)
            _samples.append((perf_counter() - started) * 1000)
            return value

        with patch("meshio.read", timed_read):
            started = perf_counter()
            preview = namespace["build_mesh_preview"](mesh_path)
            total = (perf_counter() - started) * 1000
        started = perf_counter()
        body = json.dumps(preview, separators=(",", ":")).encode()
        serialize = (perf_counter() - started) * 1000
        report["loads"].append(
            {
                "load": name,
                "parse_ms": sum(reads),
                "read_count": len(reads),
                "extraction_ms": total - sum(reads),
                "build_ms": total,
                "serialize_ms": serialize,
                "json_bytes": len(body),
            }
        )
    output = "legacy-instrumented.json"
else:
    from simassist.simulation.visualization.preview_cache import cached_mesh_preview

    artifact = uuid4()
    for name in ["cold", "warm", "warm-repeat"]:
        started = perf_counter()
        result = cached_mesh_preview(mesh_path, artifact)
        report["loads"].append(
            {
                "load": name,
                "total_ms": (perf_counter() - started) * 1000,
                "hit": result.hit,
                "json_bytes": len(result.body),
                "timings": result.timings,
            }
        )
    preview = json.loads(result.body)
    started = perf_counter()
    binary = (
        np.asarray(preview["points"], dtype="<f4").tobytes()
        + np.asarray(preview["triangles"], dtype="<u4").tobytes()
    )
    report.update(
        compact_array_bytes=len(binary),
        compact_array_pack_ms=(perf_counter() - started) * 1000,
    )
    output = "optimized.json"
triangles = np.asarray(preview["triangles"])
edges = np.sort(
    np.concatenate([triangles[:, [0, 1]], triangles[:, [1, 2]], triangles[:, [2, 0]]]),
    axis=1,
)
report.update(
    tetrahedra=preview["volume_element_count"],
    source_nodes=preview["source_node_count"],
    surface_points=preview["point_count"],
    surface_triangles=preview["triangle_count"],
    boundary_edges=len(np.unique(edges, axis=0)),
)
(root / output).write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
