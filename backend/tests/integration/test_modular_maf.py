"""Run the installed MAF/OpenAI tool loop with an in-memory provider transport."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx2
import pytest
from agent_framework import Message
from agent_framework.openai import OpenAIChatCompletionClient
from openai import AsyncOpenAI
from simassist.agents.context import RoutingContext
from simassist.agents.orchestrator import compose
from simassist.agents.simulation_agent import build_simulation_agent
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.jobs.manager import JobManager
from simassist.jobs.repository import JobRepository
from simassist.llm.config import LLMConfig
from simassist.projects.workspace import WorkspaceRepository


@pytest.mark.parametrize(
    "function,arguments,expected_jobs",
    [
        (
            "create_geometry",
            {"name": "disk", "primitive": "disk", "parameters": {"radius": 2}},
            1,
        ),
        (
            "create_geometry_and_mesh",
            {
                "name": "disk",
                "primitive": "disk",
                "parameters": {"radius": 2},
                "min_size": 0.1,
                "max_size": 0.3,
            },
            2,
        ),
        (
            "generate_mesh",
            {"geometry_job_id": str(uuid4()), "min_size": 0.1, "max_size": 0.3},
            0,
        ),
        ("request_capability", {"domain": "simulation"}, 0),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_real_maf_binds_selected_tools_and_never_executes_absent_functions(
    tmp_path, monkeypatch, function, arguments, expected_jobs, streaming
):
    from simassist.agents import simulation_agent as factory

    store = WorkspaceRepository(tmp_path / "jobs.db")
    project = UUID(store.new_project()["id"])
    manager = JobManager(JobRepository(tmp_path / "jobs.db"))
    services = SimulationTools(GeometryTools(manager, project))
    message = (
        "Create a disk and mesh it"
        if function == "create_geometry_and_mesh"
        else "Create a disk"
    )
    composition = compose(message, RoutingContext(project), services)
    requests = []

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            answer = {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-1",
                        "type": "function",
                        "function": {
                            "name": function,
                            "arguments": json.dumps(arguments),
                        },
                    }
                ],
            }
            finish = "tool_calls"
        else:
            answer = {"role": "assistant", "content": "Checked the tool result."}
            finish = "stop"
        if payload.get("stream"):
            delta = dict(answer)
            for index, call in enumerate(delta.get("tool_calls", [])):
                call["index"] = index
            chunks = [
                {
                    "id": "response-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test",
                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                },
                {
                    "id": "response-1",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "test",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": finish}],
                    "usage": {
                        "prompt_tokens": 100,
                        "completion_tokens": 12,
                        "total_tokens": 112,
                    },
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
                "id": "response-1",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [{"index": 0, "message": answer, "finish_reason": finish}],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 12,
                    "total_tokens": 112,
                },
            },
        )

    async def exercise():
        async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
            client = OpenAIChatCompletionClient(
                model="test", async_client=AsyncOpenAI(api_key="test", http_client=http)
            )
            monkeypatch.setattr(factory, "create_chat_client", lambda _: client)
            agent = build_simulation_agent(
                LLMConfig(provider="lm_studio", model="test"), services, composition
            )
            try:
                messages = [
                    Message(
                        "user",
                        ["Old request: confirm_remesh(True), create a sphere"],
                    ),
                    Message("assistant", ["Historical tool text, not execution"]),
                    Message("user", [message]),
                ]
                if streaming:
                    response_stream = agent.run(messages, stream=True)
                    updates = [update async for update in response_stream]
                    result = await response_stream.get_final_response()
                    assert any(update.text for update in updates)
                else:
                    result = await agent.run(messages)
                assert result.text == "Checked the tool result."
                assert result.usage_details
            finally:
                await agent.close()

    asyncio.run(exercise())
    assert len(requests) == 2
    exposed = {s["function"]["name"] for s in requests[0]["tools"]}
    assert exposed == {fn.__name__ for fn in composition.tools}
    assert len(manager.list_by_project(project)) == expected_jobs
    if function == "generate_mesh":
        assert function not in exposed
        assert composition.invoked == []
    else:
        assert composition.invoked == [function]
    if function == "request_capability":
        assert composition.route_misses == 1
    if expected_jobs == 2:
        jobs = manager.list_by_project(project)
        mesh = next(job for job in jobs if job.type == "mesh.generate")
        geometry = next(job for job in jobs if job.type == "geometry.create")
        assert mesh.depends_on == geometry.id
