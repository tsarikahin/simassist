from uuid import uuid4

from simassist.core.models.geometry import (
    GeometrySpec,
    PrimitiveGeometry,
    PrimitiveType,
)
from simassist.simulation.geometry.gmsh_adapter import (
    GmshGeometryAdapter,
)
from simassist.storage.local import LocalArtifactStore


def test_gmsh_geometry_artifact_integration(tmp_path):
    project_id = uuid4()

    artifact_store = LocalArtifactStore(tmp_path / "artifacts")

    geometry_adapter = GmshGeometryAdapter(
        workspace=tmp_path / "workspace",
        artifact_store=artifact_store,
        project_id=project_id,
    )

    geometry = GeometrySpec(
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

    result = geometry_adapter.create(geometry)

    artifact = artifact_store.get(result.artifact_id)

    assert artifact.project_id == project_id
    assert artifact.type.value == "geometry"
    assert artifact.filename == "geometry.step"

    geometry_path = artifact_store.resolve_path(result.artifact_id)

    assert geometry_path.exists()
    assert geometry_path.stat().st_size > 0

    metadata = geometry_adapter.inspect(result)

    assert metadata.volume_count == 1
    assert metadata.surface_count == 6
