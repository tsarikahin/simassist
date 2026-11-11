from uuid import uuid4

from simassist.core.models.geometry import (
    GeometrySpec,
    PrimitiveGeometry,
    PrimitiveType,
)
from simassist.core.models.mesh import (
    MeshRequest,
    MeshSettings,
)
from simassist.simulation.geometry.gmsh_adapter import (
    GmshGeometryAdapter,
)
from simassist.simulation.meshing.gmsh_adapter import (
    GmshMeshingAdapter,
)
from simassist.storage.local import LocalArtifactStore


def test_geometry_to_mesh_pipeline(tmp_path):
    project_id = uuid4()

    store = LocalArtifactStore(tmp_path / "artifacts")

    geometry_engine = GmshGeometryAdapter(
        workspace=tmp_path / "geometry",
        artifact_store=store,
        project_id=project_id,
    )

    meshing_engine = GmshMeshingAdapter(
        workspace=tmp_path / "meshing",
        artifact_store=store,
        project_id=project_id,
    )

    spec = GeometrySpec(
        name="Test Geometry",
        definition=PrimitiveGeometry(
            primitive=PrimitiveType.BOX,
            parameters={
                "length": 100,
                "width": 20,
                "height": 10,
            },
        ),
    )

    geometry_result = geometry_engine.create(spec)

    mesh_result = meshing_engine.generate(
        MeshRequest(
            geometry_artifact_id=geometry_result.artifact_id,
            settings=MeshSettings(
                dimension=3,
                min_size=3.0,
                max_size=5.0,
            ),
        )
    )

    mesh_artifact = store.get(mesh_result.artifact_id)

    assert mesh_artifact.type.value == "mesh"
    assert mesh_artifact.parent_ids == [geometry_result.artifact_id]

    assert mesh_result.metadata.node_count > 0
    assert mesh_result.metadata.element_count > 0

    mesh_path = store.resolve_path(mesh_result.artifact_id)

    assert mesh_path.exists()
    assert mesh_path.suffix == ".msh"

    assert len(store.list_by_project(project_id)) == 2
