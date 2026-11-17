"""Fresh canonical storage through the API, agent helpers, and worker."""

from types import SimpleNamespace
from uuid import UUID

from fastapi.testclient import TestClient
from simassist.api.dependencies import get_data_root
from simassist.api.routes import chat as chat_routes
from simassist.core import paths
from simassist.files.repository import FileRepository
from simassist.jobs.models import JobStatus
from simassist.main import app
from simassist.workers.runner import SimulationWorker


def test_fresh_canonical_runtime_workflow(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    (checkout / "backend").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPOSITORY_ROOT", checkout)
    monkeypatch.delenv("SIMASSIST_DATA_DIR", raising=False)
    monkeypatch.chdir(checkout / "backend")
    canonical = checkout / "data"
    assert get_data_root() == canonical
    assert not canonical.exists()

    class Agent:
        async def run(self, *args, **kwargs):
            return SimpleNamespace(text="Development chat persisted.")

        async def close(self):
            pass

    # Keep model-server availability independent of runtime storage acceptance.
    monkeypatch.setattr(chat_routes, "build_simulation_agent", lambda **kwargs: Agent())
    with TestClient(app) as client:
        assert not canonical.exists()
        project_response = client.post(
            "/api/workspace/projects", json={"name": "Fresh runtime"}
        )
        assert project_response.status_code == 200
        project = UUID(project_response.json()["id"])
        base = f"/api/projects/{project}"
        chat_base = f"/api/workspace/projects/{project}/chats"
        chat_response = client.post(chat_base)
        assert chat_response.status_code == 200
        chat = chat_response.json()["id"]
        worker = SimulationWorker()
        assert worker.data_root == canonical

        created = client.post(
            "/api/jobs",
            json={
                "project_id": str(project),
                "type": "geometry.create",
                "input": {
                    "name": "Fresh box",
                    "units": "mm",
                    "definition": {
                        "source": "primitive",
                        "primitive": "box",
                        "parameters": {"length": 4, "width": 3, "height": 2},
                    },
                },
            },
        )
        assert created.status_code == 202
        geometry = worker.process_next()
        assert geometry.status == JobStatus.COMPLETED, geometry.error
        step = worker.artifact_store.resolve_path(UUID(geometry.result["artifact_id"]))
        uploaded = client.post(
            f"{base}/files",
            files={
                "file": ("fresh.step", step.read_bytes(), "application/octet-stream")
            },
        )
        assert uploaded.status_code == 200, uploaded.text
        files = FileRepository(get_data_root())
        imported_id, _ = files.submit_import(
            project,
            uploaded.json()["file_id"],
            {"dimension": 3, "min_size": 0.8, "max_size": 1.2},
        )
        imported = worker.process_next()
        assert imported.id == imported_id
        assert imported.status == JobStatus.COMPLETED, imported.error
        mesh = worker.process_next()
        assert mesh.status == JobStatus.COMPLETED, mesh.error
        assert (
            client.put(
                f"{base}/active-geometry", json={"geometry_job_id": str(imported_id)}
            ).status_code
            == 200
        )

        response = client.post(
            "/api/chat",
            json={
                "project_id": str(project),
                "chat_id": chat,
                "message": "Remesh it using min 0.4 mm and max 0.6 mm",
            },
        )
        assert response.status_code == 200, response.text
        remesh_id = UUID(response.json()["submitted_job_ids"][0])
        remeshed = worker.process_next()
        assert remeshed.id == remesh_id
        assert remeshed.status == JobStatus.COMPLETED, remeshed.error
        history = client.get(f"{chat_base}/{chat}/messages").json()
        assert [message["role"] for message in history] == ["user", "assistant"]

    # Reopen both services from the other launch directory against the same data.
    monkeypatch.chdir(checkout)
    restarted = SimulationWorker()
    assert restarted.data_root == canonical
    assert restarted.repository.get(remesh_id).status == JobStatus.COMPLETED
    with TestClient(app) as client:
        assert client.get(f"{chat_base}/{chat}/messages").json() == history
        versions = client.get(f"{base}/geometries/{imported_id}/meshes").json()
        assert {version["job_id"] for version in versions} == {
            str(mesh.id),
            str(remesh_id),
        }
        for version in versions:
            assert (
                client.get(
                    f"{base}/artifacts/{version['artifact_id']}/download"
                ).status_code
                == 200
            )

    assert not (checkout / "backend" / "data").exists()
    assert all(
        path.is_relative_to(canonical) for path in checkout.rglob("*") if path.is_file()
    )
