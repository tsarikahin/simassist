"""Real Gmsh boolean workflows; run with the backend's Gmsh dependencies."""

import math
from uuid import uuid4

import pytest

pytest.importorskip("gmsh")

from simassist.api.routes.mesh_previews import build_mesh_preview
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshRequest, MeshSettings
from simassist.simulation.geometry.gmsh_adapter import GmshGeometryAdapter
from simassist.simulation.meshing.gmsh_adapter import GmshMeshingAdapter
from simassist.simulation.visualization.gmsh_preview import GmshPreviewService
from simassist.storage.local import LocalArtifactStore


@pytest.mark.parametrize("operation", ["cut", "fuse", "intersect"])
def test_2d_boolean_disk_shapes(tmp_path, operation):
    project_id = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    geo_adapter = GmshGeometryAdapter(tmp_path / "geo", store, project_id)
    spec = GeometrySpec.model_validate(
        {
            "name": f"disk {operation}",
            "definition": {
                "source": "csg",
                "operation": operation,
                "operands": [
                    {"primitive": "disk", "parameters": {"radius": 2}},
                    {"primitive": "disk", "parameters": {"radius": 1}},
                ],
            },
        }
    )
    result = geo_adapter.create(spec)
    assert result.metadata.dimension == 2
    assert result.metadata.surface_count == 1
    assert store.resolve_path(result.artifact_id).exists()
    preview = GmshPreviewService(tmp_path / "preview", store, project_id)
    preview_id = preview.generate(result.artifact_id)
    assert store.resolve_path(preview_id).exists()

    mesh_adapter = GmshMeshingAdapter(tmp_path / "mesh", store, project_id)
    mesh = mesh_adapter.generate(
        MeshRequest(
            geometry_artifact_id=result.artifact_id,
            settings=MeshSettings(
                dimension=2,
                element_family="triangular",
                min_size=0.15,
                max_size=0.4,
            ),
        )
    )
    assert mesh.metadata.element_count > 0
    surface = build_mesh_preview(store.resolve_path(mesh.artifact_id))
    assert surface["dimension"] == 2
    assert surface["triangle_count"] > 0

    if operation == "cut":
        import gmsh

        gmsh.initialize()
        try:
            gmsh.model.add("inspect_annulus_area")
            gmsh.model.occ.importShapes(str(store.resolve_path(result.artifact_id)))
            gmsh.model.occ.synchronize()
            faces = gmsh.model.getEntities(2)
            assert len(faces) == 1
            area = gmsh.model.occ.getMass(2, faces[0][1])
            assert area == pytest.approx(3 * math.pi, rel=1e-4)
        finally:
            gmsh.finalize()
