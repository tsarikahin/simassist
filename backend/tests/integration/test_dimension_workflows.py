"""Real Gmsh/meshio end-to-end tests. Run on a machine with backend dependencies."""

from uuid import uuid4

import pytest
from simassist.api.routes.mesh_previews import build_mesh_preview
from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshRequest, MeshSettings
from simassist.simulation.geometry.gmsh_adapter import GmshGeometryAdapter
from simassist.simulation.meshing.gmsh_adapter import GmshMeshingAdapter
from simassist.simulation.visualization.gmsh_preview import GmshPreviewService
from simassist.storage.local import LocalArtifactStore


@pytest.mark.parametrize(
    ("primitive", "params", "dim", "family", "cell_type"),
    [
        ("line", {"length": 10}, 1, "line", "line"),
        ("square", {"size": 1}, 2, "triangular", "triangle"),
        ("square", {"size": 1}, 2, "quadrilateral", "quad"),
        ("rectangle", {"width": 2, "height": 1}, 2, "quadrilateral", "quad"),
        ("box", {"length": 2, "width": 1, "height": 1}, 3, "tetrahedral", "tetra"),
    ],
)
def test_dimension_pipeline(tmp_path, primitive, params, dim, family, cell_type):
    project_id = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")
    geometry_adapter = GmshGeometryAdapter(tmp_path / "geometry", store, project_id)
    mesh_adapter = GmshMeshingAdapter(tmp_path / "meshing", store, project_id)
    spec = GeometrySpec.model_validate(
        {
            "name": "dimension test",
            "definition": {
                "source": "primitive",
                "primitive": primitive,
                "parameters": params,
            },
        }
    )
    geometry = geometry_adapter.create(spec)
    assert geometry.metadata.dimension == dim
    preview_service = GmshPreviewService(tmp_path / "previews", store, project_id)
    preview_artifact_id = preview_service.generate(geometry.artifact_id)
    assert store.resolve_path(preview_artifact_id).exists()
    minimum, maximum = (0.1, 0.25) if dim == 2 else (0.4, 0.8)
    mesh = mesh_adapter.generate(
        MeshRequest(
            geometry_artifact_id=geometry.artifact_id,
            settings=MeshSettings(
                dimension=dim, element_family=family, min_size=minimum, max_size=maximum
            ),
        )
    )
    assert mesh.metadata.element_count > 0
    preview = build_mesh_preview(store.resolve_path(mesh.artifact_id))
    assert preview["dimension"] == dim
    assert preview["point_count"] > 0
    if dim == 1:
        assert preview["line_count"] > 0
    elif dim == 2:
        if family == "quadrilateral":
            assert preview["quad_count"] > 0
            assert preview["triangle_count"] == 0
        else:
            assert preview["triangle_count"] > 0
            assert preview["quad_count"] == 0
    else:
        assert preview["triangle_count"] > 0
