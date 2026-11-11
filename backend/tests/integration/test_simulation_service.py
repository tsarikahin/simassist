from uuid import uuid4

from simassist.core.models.artifact import ArtifactType
from simassist.core.models.geometry import (
    GeometrySpec,
    PrimitiveGeometry,
    PrimitiveType,
)
from simassist.core.models.mesh import (
    MeshRequest,
    MeshSettings,
)
from simassist.services.factory import create_simulation_service
from simassist.storage.local import LocalArtifactStore


def test_simulation_service_pipeline(tmp_path):
    project_id = uuid4()

    store = LocalArtifactStore(tmp_path / "artifacts")

    service = create_simulation_service(
        project_id=project_id,
        workspace=tmp_path / "workspace",
        artifact_store=store,
    )

    # 1. Create geometry through the service.
    spec = GeometrySpec(
        name="Generic Test Geometry",
        definition=PrimitiveGeometry(
            primitive=PrimitiveType.BOX,
            parameters={
                "length": 100,
                "width": 20,
                "height": 10,
            },
        ),
    )

    geometry = service.create_geometry(spec)

    assert geometry.engine == "gmsh"

    geometry_artifact = store.get(geometry.artifact_id)

    assert geometry_artifact.type == ArtifactType.GEOMETRY

    # 2. Inspect geometry using the service.
    metadata = service.inspect_geometry(geometry)

    assert metadata.volume_count == 1
    assert metadata.surface_count == 6

    # 3. Generate mesh through the service.
    mesh = service.generate_mesh(
        MeshRequest(
            geometry_artifact_id=geometry.artifact_id,
            settings=MeshSettings(
                dimension=3,
                min_size=3.0,
                max_size=5.0,
            ),
        )
    )

    assert mesh.engine == "gmsh"
    assert mesh.metadata.node_count > 0
    assert mesh.metadata.element_count > 0

    # 4. Verify artifact relationships.
    mesh_artifact = store.get(mesh.artifact_id)

    assert mesh_artifact.type == ArtifactType.MESH
    assert mesh_artifact.parent_ids == [geometry.artifact_id]

    # 5. Verify both artifacts are registered.
    artifacts = store.list_by_project(project_id)

    assert len(artifacts) == 2
