"""Remesh submission through the public chat and mesh-version APIs."""

import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from simassist.api.dependencies import get_job_manager, get_project_context_repository
from simassist.api.routes import chat as routes
from simassist.api.routes.mesh_versions import router as versions_router
from simassist.jobs.manager import JobManager
from simassist.projects.context import ProjectContextRepository
from simassist.projects.remesh_proposals import RemeshProposalStore
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("mode", ["explicit", "followup", "converted"])
def test_explicit_remesh_submits_once_and_refreshes_versions(
    tmp_path, monkeypatch, streaming, mode
):
    worker = SimulationWorker(tmp_path)
    manager = JobManager(worker.repository)
    store = WorkspaceRepository(tmp_path / "jobs.db")
    context = ProjectContextRepository(store.db_path, worker.repository)
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    geometry, original = manager.submit_geometry_mesh(
        project,
        {
            "name": "box",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "box",
                "parameters": {"length": 100, "width": 20, "height": 10},
            },
        },
        {"dimension": 3, "min_size": 2, "max_size": 5, "element_family": "tetrahedral"},
    )
    while worker.process_next():
        pass
    context.set_active_geometry(project, geometry.id)
    context.set_selected_mesh(project, geometry.id, original.id)

    class NoToolsAgent:
        async def run(self, *args, **kwargs):
            return SimpleNamespace(text=f"Queued mesh job {geometry.id}")

        async def close(self):
            pass

    monkeypatch.setattr(routes, "_workspace", lambda: store)
    monkeypatch.setattr(routes, "build_simulation_agent", lambda **_: NoToolsAgent())
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(versions_router)
    app.dependency_overrides[get_job_manager] = lambda: manager
    app.dependency_overrides[get_project_context_repository] = lambda: context
    endpoint = "/api/chat/stream" if streaming else "/api/chat"

    def body(message):
        return {
            "project_id": str(project),
            "chat_id": str(chat),
            "request_id": str(uuid4()),
            "message": message,
        }

    with TestClient(app) as client:
        if mode == "followup":
            response = client.post(endpoint, json=body("Make it finer."))
            assert response.status_code == 200
            assert len(manager.list_by_project(project)) == 2
            assert RemeshProposalStore(store.db_path).get(chat)
        messages = {
            "followup": "min 0.5 max 1 mm",
            "explicit": "Remesh it using min 0.5 mm and max 1 mm",
            "converted": "Remesh it using min 0.05 cm and max 0.001 m",
        }
        request = body(messages[mode])
        response = client.post(endpoint, json=request)
        assert response.status_code == 200
        result = (
            json.loads(response.text.split("event: done\ndata: ")[1])
            if streaming
            else response.json()
        )
        assert len(result["submitted_job_ids"]) == 1
        new_id = UUID(result["submitted_job_ids"][0])
        assert new_id not in {geometry.id, original.id}
        job = manager.get(new_id)
        assert job.type == "mesh.generate"
        assert job.project_id == project
        assert (
            job.input["geometry_artifact_id"]
            == manager.get(geometry.id).result["artifact_id"]
        )
        assert job.input["settings"]["min_size"] == 0.5
        assert job.input["settings"]["max_size"] == 1
        assert str(new_id) in result["message"]
        assert client.post(endpoint, json=request).status_code == 200
        assert len(manager.list_by_project(project)) == 3
        assert not RemeshProposalStore(store.db_path).get(chat)
        assert worker.process_next()
        versions = client.get(
            f"/api/projects/{project}/geometries/{geometry.id}/meshes"
        ).json()
        assert {v["job_id"] for v in versions} == {str(original.id), str(new_id)}
        assert context.get(project).selected_mesh_job_id == original.id
        assert (
            manager.get(new_id).result["metadata"]["node_count"]
            > (manager.get(original.id).result["metadata"]["node_count"])
        )
