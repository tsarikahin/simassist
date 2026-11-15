from uuid import uuid4

from simassist.core.models.artifact import ArtifactType
from simassist.core.models.geometry import (
    GeometrySpec,
    PrimitiveGeometry,
    PrimitiveType,
)
from simassist.simulation.geometry.gmsh_adapter import (
    GmshGeometryAdapter,
)
from simassist.simulation.visualization.gmsh_preview import (
    GeometryPreview,
    GmshPreviewService,
)
from simassist.storage.local import LocalArtifactStore


def test_geometry_preview_pipeline(tmp_path):
    project_id = uuid4()
    store = LocalArtifactStore(tmp_path / "artifacts")

    geometry_engine = GmshGeometryAdapter(
        workspace=tmp_path / "geometry",
        artifact_store=store,
        project_id=project_id,
    )

    spec = GeometrySpec(
        name="Preview Test",
        definition=PrimitiveGeometry(
            primitive=PrimitiveType.CYLINDER,
            parameters={
                "radius": 10,
                "height": 50,
            },
        ),
    )

    geometry = geometry_engine.create(spec)

    preview_service = GmshPreviewService(
        workspace=tmp_path / "previews",
        artifact_store=store,
        project_id=project_id,
    )

    preview_id = preview_service.generate(geometry.artifact_id)

    artifact = store.get(preview_id)

    assert artifact.type == ArtifactType.GEOMETRY_PREVIEW
    assert artifact.parent_ids == [geometry.artifact_id]

    preview_path = store.resolve_path(preview_id)

    preview = GeometryPreview.model_validate_json(
        preview_path.read_text(encoding="utf-8")
    )

    assert preview.point_count > 0
    assert preview.triangle_count > 0
    assert len(preview.points) == preview.point_count
    assert len(preview.triangles) == preview.triangle_count

    for triangle in preview.triangles:
        assert all(0 <= index < preview.point_count for index in triangle)
