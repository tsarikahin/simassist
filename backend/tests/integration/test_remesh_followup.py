"""Exact annulus -> refinement -> numeric sizes through chat, MAF and the worker."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx2
import pytest
from agent_framework.openai import OpenAIChatCompletionClient
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import AsyncOpenAI
from simassist.agents import simulation_agent as factory
from simassist.api.dependencies import get_job_manager, get_project_context_repository
from simassist.api.routes import chat as routes
from simassist.jobs.manager import JobManager
from simassist.projects.context import ProjectContextRepository
from simassist.projects.remesh_proposals import RemeshProposalStore
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker

CREATE = (
    "Create a new 2D annulus with inner radius 1 mm and outer radius 2 mm, "
    "then generate a triangular mesh with sizes 0.05–0.1 mm."
)
REFINE = "Make it finer."
SIZES = "Use 0.025–0.05 mm."


@pytest.mark.parametrize("streaming", [False, True])
def test_annulus_followup_submits_one_new_mesh_version(
    tmp_path, monkeypatch, streaming
):
    worker = SimulationWorker(tmp_path)
    manager = JobManager(worker.repository)
    context = ProjectContextRepository(tmp_path / "jobs.db", worker.repository)
    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    calls = []
    clients = []
    actions = {
        CREATE: [
            (
                "create_boolean_geometry_and_mesh",
                {
                    "name": "annulus_1_2mm",
                    "operation": "cut",
                    "operands": [
                        {"primitive": "disk", "parameters": {"radius": 2}},
                        {"primitive": "disk", "parameters": {"radius": 1}},
                    ],
                    "units": "mm",
                    "dimension": 2,
                    "min_size": 0.05,
                    "max_size": 0.1,
                    "element_family": "triangular",
                },
            )
        ],
        REFINE: [("get_active_geometry", {}), ("generate_mesh", {})],
        SIZES: [
            ("get_active_geometry", {}),
            (
                "generate_mesh",
                {
                    "min_size": 0.025,
                    "max_size": 0.05,
                    "element_family": "triangular",
                },
            ),
        ],
    }

    def provider(request):
        payload = json.loads(request.content)
        messages = payload["messages"]
        current_index = max(
            i for i, message in enumerate(messages) if message["role"] == "user"
        )
        current = messages[current_index]["content"]
        completed = sum(
            message["role"] == "tool" for message in messages[current_index + 1 :]
        )
        plan = actions[current]
        available = {item["function"]["name"] for item in payload["tools"]}
        mesh_schema = next(
            item["function"]
            for item in payload["tools"]
            if item["function"]["name"] == "generate_mesh"
        )
        assert "new mesh version" in mesh_schema["description"]
        assert (
            "clarification"
            in mesh_schema["parameters"]["properties"]["min_size"]["description"]
        )
        assert (
            "triangular/quadrilateral"
            in mesh_schema["parameters"]["properties"]["element_family"]["description"]
        )
        calls.append((current, available))
        if current != CREATE:
            assert "generate_mesh" in available
            assert "create_boolean_geometry_and_mesh" not in available
        if completed < len(plan):
            name, arguments = plan[completed]
            assert name in available
            answer = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"call-{len(calls)}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(arguments)},
                    }
                ],
            }
            finish = "tool_calls"
        else:
            answer = {
                "role": "assistant",
                "content": "Current sizes are 0.05–0.1 mm. Please supply smaller bounds."
                if current == REFINE
                else "Queued the requested workflow.",
            }
            finish = "stop"
        if payload.get("stream"):
            for index, call in enumerate(answer.get("tool_calls", [])):
                call["index"] = index
            chunks = [
                {
                    "id": "response",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test",
                    "choices": [{"index": 0, "delta": answer, "finish_reason": None}],
                },
                {
                    "id": "response",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                },
            ]
            return httpx2.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content="".join(
                    "data: " + json.dumps(chunk) + "\n\n" for chunk in chunks
                )
                + "data: [DONE]\n\n",
            )
        return httpx2.Response(
            200,
            json={
                "id": "response",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [{"index": 0, "message": answer, "finish_reason": finish}],
            },
        )

    def client_factory(_):
        http = httpx2.AsyncClient(transport=httpx2.MockTransport(provider))
        clients.append(http)
        return OpenAIChatCompletionClient(
            model="test", async_client=AsyncOpenAI(api_key="test", http_client=http)
        )

    monkeypatch.setattr(factory, "create_chat_client", client_factory)
    monkeypatch.setattr(routes, "_workspace", lambda: store)
    app = FastAPI()
    app.include_router(routes.router)
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

    try:
        with TestClient(app) as client:
            assert client.post(endpoint, json=body(CREATE)).status_code == 200
            while worker.process_next():
                pass
            initial = manager.list_by_project(project)
            assert len(initial) == 2
            assert all(job.status == "completed" for job in initial)
            geometry = next(job for job in initial if job.type == "geometry.create")
            original = next(job for job in initial if job.type == "mesh.generate")
            assert geometry.result["metadata"]["dimension"] == 2
            assert geometry.result["metadata"]["curve_count"] == 2
            context.set_active_geometry(project, geometry.id)
            context.set_selected_mesh(project, geometry.id, original.id)
            assert client.post(endpoint, json=body(REFINE)).status_code == 200
            proposal = RemeshProposalStore(context.db_path).get(chat)
            assert proposal["min_size"] == 0.05
            assert proposal["max_size"] == 0.1
            assert len(manager.list_by_project(project)) == 2
            request = body(SIZES)
            response = client.post(endpoint, json=request)
            assert response.status_code == 200
            if streaming:
                assert "event: jobs" in response.text
                assert "event: done" in response.text
            while worker.process_next():
                pass
            jobs = manager.list_by_project(project)
            assert len(jobs) == 3
            assert all(job.status == "completed" for job in jobs)
            finer = next(
                job for job in jobs if job.id not in {geometry.id, original.id}
            )
            assert finer.input["geometry_artifact_id"] == geometry.result["artifact_id"]
            assert finer.input["settings"]["min_size"] == 0.025
            assert finer.input["settings"]["max_size"] == 0.05
            assert finer.input["settings"]["element_family"] == "triangular"
            assert (
                finer.result["metadata"]["node_count"]
                > original.result["metadata"]["node_count"]
            )
            assert not RemeshProposalStore(context.db_path).get(chat)
            # The old mesh stays selected until the viewer chooses the new one.
            assert context.get(project).selected_mesh_job_id == original.id
            count = len(calls)
            assert client.post(endpoint, json=request).status_code == 200
            assert len(calls) == count
            assert len(manager.list_by_project(project)) == 3
            assert [item["role"] for item in store.messages(project, chat)] == [
                "user",
                "assistant",
            ] * 3
    finally:

        async def close_clients():
            for client in clients:
                await client.aclose()

        asyncio.run(close_clients())
