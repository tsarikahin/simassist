from uuid import uuid4

from fastapi.testclient import TestClient
from simassist.api.dependencies import get_artifact_store
from simassist.core.models.artifact import (
    ArtifactCreate,
    ArtifactType,
)
from simassist.main import app
from simassist.storage.local import LocalArtifactStore


def test_artifact_api(tmp_path):
    store = LocalArtifactStore(tmp_path / "artifacts")
    project_id = uuid4()

    source = tmp_path / "geometry.step"
    source.write_bytes(b"test geometry content")

    artifact = store.save(
        ArtifactCreate(
            project_id=project_id,
            type=ArtifactType.GEOMETRY,
            source_path=source,
        )
    )

    app.dependency_overrides[get_artifact_store] = lambda: store

    try:
        with TestClient(app) as client:
            base = f"/api/projects/{project_id}/artifacts"

            response = client.get(base)
            assert response.status_code == 200
            assert len(response.json()) == 1

            response = client.get(f"{base}/{artifact.id}")
            assert response.status_code == 200
            assert response.json()["id"] == str(artifact.id)

            response = client.get(f"{base}/{artifact.id}/download")
            assert response.status_code == 200
            assert response.content == b"test geometry content"

            # Cross-project artifact access must fail.
            other_project_id = uuid4()

            response = client.get(
                f"/api/projects/{other_project_id}/artifacts/{artifact.id}"
            )
            assert response.status_code == 404

    finally:
        app.dependency_overrides.clear()
