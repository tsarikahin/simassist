from uuid import uuid4

from simassist.core.models.artifact import (
    ArtifactCreate,
    ArtifactType,
)
from simassist.storage.local import LocalArtifactStore


def test_save_and_retrieve_artifact(tmp_path):
    store = LocalArtifactStore(tmp_path / "storage")

    project_id = uuid4()

    source = tmp_path / "geometry.step"
    source.write_text("example geometry", encoding="utf-8")

    artifact = store.save(
        ArtifactCreate(
            project_id=project_id,
            type=ArtifactType.GEOMETRY,
            source_path=source,
        )
    )

    assert artifact.project_id == project_id
    assert artifact.type == ArtifactType.GEOMETRY
    assert artifact.size_bytes > 0
    assert len(artifact.sha256) == 64

    loaded = store.get(artifact.id)

    assert loaded.id == artifact.id
    assert (
        store.resolve_path(artifact.id).read_text(encoding="utf-8")
        == "example geometry"
    )

    artifacts = store.list_by_project(project_id)
    assert len(artifacts) == 1
    assert artifacts[0].id == artifact.id
