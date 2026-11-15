"""Exercise both API contracts without a model server or real tool submissions."""

import asyncio
import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from simassist.api.dependencies import get_job_manager, get_project_context_repository
from simassist.api.routes import chat as routes
from simassist.projects.workspace import WorkspaceRepository


class FakeStream:
    def __init__(self, agent):
        self.agent = agent

    async def __aiter__(self):
        yield SimpleNamespace(text="first ")
        self.agent.tools.submitted_job_ids.append(str(uuid4()))
        if self.agent.fail:
            raise RuntimeError("private provider error")
        yield SimpleNamespace(text="second")

    async def get_final_response(self):
        return SimpleNamespace(text="first second")


class FakeAgent:
    def __init__(self, tools):
        self.tools = tools
        self.closed = False
        self.fail = False
        self.inputs = []

    def run(self, messages, stream=False, options=None):
        self.inputs.append(messages)
        if stream:
            return FakeStream(self)

        async def response():
            if self.fail:
                raise RuntimeError("private provider error")
            return SimpleNamespace(text="first second")

        return response()

    async def close(self):
        self.closed = True


@pytest.fixture
def api(tmp_path, monkeypatch):
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    agents = []
    monkeypatch.setattr(routes, "_workspace", lambda: store)
    monkeypatch.setattr(
        routes, "_simulation_tools", lambda *args: SimpleNamespace(submitted_job_ids=[])
    )
    monkeypatch.setattr(routes, "simulation_agent_tools", lambda _: [])

    def build(**kwargs):
        agent = FakeAgent(kwargs["simulation_tools"])
        agents.append(agent)
        return agent

    monkeypatch.setattr(routes, "build_simulation_agent", build)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_job_manager] = lambda: None
    app.dependency_overrides[get_project_context_repository] = lambda: None
    with TestClient(app) as client:
        yield client, store, project, chat, agents


def body(project, chat, message="hello"):
    return {
        "project_id": str(project),
        "chat_id": str(chat),
        "message": message,
        "request_id": str(uuid4()),
    }


def test_sync_sse_persistence_replay_and_roles(api):
    client, store, project, chat, agents = api
    first = body(project, chat)
    response = client.post("/api/chat", json=first)
    assert response.status_code == 200
    assert client.post("/api/chat", json=first).json() == response.json()
    assert len(agents) == 1
    second = body(project, chat, "mesh question")
    streamed = client.post("/api/chat/stream", json=second)
    assert streamed.status_code == 200
    for event in ("status", "delta", "jobs", "done"):
        assert f"event: {event}" in streamed.text
    messages = store.messages(project, chat)
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[-1]["content"] == "first second"
    assert [m.role for m in agents[-1].inputs[0]] == ["user", "assistant", "user"]
    assert all(a.closed for a in agents)
    assert "event: done" in client.post("/api/chat/stream", json=second).text
    assert len(agents) == 2
    assert (
        client.post("/api/chat", json={**first, "message": "changed"}).status_code
        == 409
    )
    assert client.post("/api/chat", json=body(uuid4(), chat)).status_code == 404


def test_failed_stream_after_submission_is_not_completed(api, monkeypatch):
    client, store, project, chat, agents = api
    original = routes.build_simulation_agent

    def failing(**kwargs):
        agent = original(**kwargs)
        agent.fail = True
        return agent

    monkeypatch.setattr(routes, "build_simulation_agent", failing)
    request = body(project, chat)
    response = client.post("/api/chat/stream", json=request)
    assert "event: error" in response.text
    assert "event: done" not in response.text
    assert "private provider error" not in response.text
    assert len(store.messages(project, chat)) == 1
    assert store.context_messages(project, chat) == []
    with store._connect() as db:
        turn = db.execute("SELECT * FROM conversation_turns").fetchone()
        assert turn["status"] == "failed"
        assert len(json.loads(turn["job_ids"])) == 1
    assert client.post("/api/chat", json=request).status_code == 409
    assert agents[-1].closed


def test_concurrent_requests_and_interrupted_stream(api):
    _, store, project, chat, agents = api

    async def exercise():
        request = routes.ChatRequest(**body(project, chat))
        response = await routes.stream_chat(request, None, None)
        iterator = response.body_iterator
        await anext(iterator)  # Holds chat ownership while waiting on the model.
        with pytest.raises(HTTPException) as conflict:
            await routes.chat(routes.ChatRequest(**body(project, chat)), None, None)
        assert conflict.value.status_code == 409
        other = UUID(store.new_chat(project)["id"])
        await routes.chat(routes.ChatRequest(**body(project, other)), None, None)
        await iterator.aclose()
        assert agents[0].closed
        with store._connect() as db:
            turn = db.execute(
                "SELECT * FROM conversation_turns WHERE request_id=?",
                (str(request.request_id),),
            ).fetchone()
            assert turn["status"] == "interrupted"
        assert len(store.messages(project, chat)) == 1

    asyncio.run(exercise())


def test_project_mesh_truth_and_chat_local_confirmation(tmp_path):
    from simassist.agents.tools.geometry import GeometryTools
    from simassist.agents.tools.simulation_tools import SimulationTools
    from simassist.jobs.manager import JobManager
    from simassist.projects.context import ProjectContextRepository
    from simassist.workers.runner import SimulationWorker

    worker = SimulationWorker(data_root=tmp_path)
    manager = JobManager(worker.repository)
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    a, b = [UUID(store.new_chat(project)["id"]) for _ in range(2)]
    geometry_job, _ = manager.submit_geometry_mesh(
        project_id=project,
        geometry_payload={
            "name": "Shared square",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "square",
                "parameters": {"size": 2},
            },
        },
        mesh_settings={
            "dimension": 2,
            "min_size": 0.1,
            "max_size": 0.3,
            "element_family": "triangular",
        },
    )
    worker.process_next()
    worker.process_next()
    context = ProjectContextRepository(tmp_path / "jobs.db", worker.repository)
    context.set_active_geometry(project, geometry_job.id)

    def tools(chat):
        return SimulationTools(
            GeometryTools(manager, project), context, proposal_scope=chat
        )

    agent_a, agent_b = tools(a), tools(b)
    info = json.loads(agent_b.get_active_mesh_info())
    assert info["mesh_version_count"] == 1
    assert info["latest_completed_mesh"]["metadata"]["node_count"] > 0
    assert "viewer" in info["source"]
    count = len(manager.list_by_project(project))
    proposal = json.loads(agent_a.generate_mesh(element_family="quadrilateral"))
    assert proposal["clarification_required"]
    assert len(manager.list_by_project(project)) == count
    assert not json.loads(agent_b.confirm_remesh(True))["ok"]
    # A fresh tools instance can confirm only its own persisted proposal.
    assert json.loads(tools(a).confirm_remesh(True))["ok"]
    assert len(manager.list_by_project(project)) == count + 1
    assert not json.loads(tools(a).confirm_remesh(True))["ok"]
    assert len(manager.list_by_project(project)) == count + 1
    # Recreate a proposal, then delete its owning chat without removing meshes.
    tools(a).generate_mesh(element_family="quadrilateral")
    store.delete_chat(project, a)
    assert not json.loads(tools(a).get_pending_remesh())["ok"]
    assert json.loads(agent_b.get_active_mesh_info())["mesh_version_count"] == 1
