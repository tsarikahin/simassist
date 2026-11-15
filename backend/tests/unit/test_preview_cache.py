"""Boundary correctness, immutable caching, warm HTTP metadata and cache recovery."""

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import meshio
import numpy as np
import pytest
from simassist.simulation.visualization.mesh_preview import build_mesh_preview
from simassist.simulation.visualization.preview_cache import cached_mesh_preview


def write_mesh(path):
    meshio.write(
        path,
        meshio.Mesh(
            points=np.array(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1]], dtype=float
            ),
            cells=[("tetra", np.array([[0, 1, 2, 3], [0, 2, 1, 4]]))],
        ),
        file_format="gmsh22",
    )


def test_cache_skips_parse_and_preserves_bytes(tmp_path, monkeypatch):
    path = tmp_path / "mesh.msh"
    write_mesh(path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    artifact = uuid4()
    cold = cached_mesh_preview(path, artifact)
    assert not cold.hit

    def forbidden(*args, **kwargs):
        raise AssertionError("warm load must not parse the MSH")

    monkeypatch.setattr(
        "simassist.simulation.visualization.preview_cache.build_mesh_preview", forbidden
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        warm = list(pool.map(lambda _: cached_mesh_preview(path, artifact), range(8)))
    assert all(item.hit and item.body == cold.body for item in warm)
    response = warm[0].response(uuid4(), artifact)
    assert response.headers["x-preview-cache"] == "HIT"
    assert "cache;dur=" in response.headers["server-timing"]
    assert json.loads(response.body)["mesh_artifact_id"] == str(artifact)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_cache_recovers_from_corruption_and_source_change(tmp_path):
    path = tmp_path / "mesh.msh"
    write_mesh(path)
    artifact = uuid4()
    first = cached_mesh_preview(path, artifact)
    cache = next((tmp_path / ".simassist-preview-cache").glob("v[0-9].json"))
    cache.write_bytes(b"x" * len(first.body))
    assert not cached_mesh_preview(path, artifact).hit
    assert cached_mesh_preview(path, artifact).hit
    cache.with_suffix(".meta.json").write_text("null")
    assert not cached_mesh_preview(path, artifact).hit
    mesh = meshio.read(path)
    mesh.points *= 2
    meshio.write(path, mesh, file_format="gmsh22")
    changed = cached_mesh_preview(path, artifact)
    assert not changed.hit
    assert max(p[0] for p in json.loads(changed.body)["points"]) == 2
    assert not cached_mesh_preview(path, uuid4()).hit


def test_boundary_normals_point_outward_and_do_not_duplicate_shared_faces(tmp_path):
    path = tmp_path / "mesh.msh"
    write_mesh(path)
    preview = build_mesh_preview(path)
    points = np.array(preview["points"])
    cells = np.array(preview["triangles"])
    assert len(cells) == 6
    for triangle in points[cells]:
        normal = np.cross(triangle[1] - triangle[0], triangle[2] - triangle[0])
        assert np.dot(normal, triangle.mean(axis=0) - np.array([0.2, 0.2, 0])) > 0


def test_non_manifold_tetra_faces_rejected(tmp_path):
    path = tmp_path / "mesh.msh"
    meshio.write(
        path,
        meshio.Mesh(
            points=np.array(
                [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [0, 0, -1], [0, 0, 2]],
                float,
            ),
            cells=[("tetra", np.array([[0, 1, 2, 3], [0, 1, 2, 4], [0, 1, 2, 5]]))],
        ),
        file_format="gmsh22",
    )
    with pytest.raises(ValueError, match="Non-manifold"):
        build_mesh_preview(path)
