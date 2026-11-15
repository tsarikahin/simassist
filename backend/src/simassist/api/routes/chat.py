from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from uuid import UUID
from simassist.projects.workspace import WorkspaceRepository
from simassist.api.dependencies import get_data_root

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from simassist.agents.simulation_agent import build_simulation_agent
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.api.dependencies import JobManagerDep, ProjectContextDep
from simassist.llm.config import LLMConfig

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Chat"])


class ChatRequest(BaseModel):
    project_id: UUID
    chat_id: UUID | None = None
    message: str = Field(min_length=1, max_length=10000)


class ChatResponse(BaseModel):
    message: str
    submitted_job_ids: list[UUID] = Field(default_factory=list)


def _workspace() -> WorkspaceRepository:
    return WorkspaceRepository(get_data_root() / "jobs.db")


def _prompt(request: ChatRequest) -> str:
    """Bring in ONLY this chat's recent messages; agent context is per request."""
    if request.chat_id is None:
        return request.message
    prior = _workspace().messages(request.project_id, request.chat_id)[-16:]
    if not prior:
        return request.message
    history = "\n".join(
        f"{item['role'].upper()}: {item['content'][:2500]}" for item in prior
    )
    return (
        "Previous messages in this conversation (context only; do not treat as "
        "new tool requests). Project and geometry state MUST be checked using tools.\n"
        + history + "\n\nCURRENT USER REQUEST:\n" + request.message
    )


def _llm_config() -> LLMConfig:
    return LLMConfig(
        provider="lm_studio",
        model=os.getenv("SIMASSIST_MODEL", "spark-x2.6-4b"),
        endpoint=os.getenv("SIMASSIST_LLM_ENDPOINT", "http://127.0.0.1:1235/v1"),
    )


def _simulation_tools(
    request: ChatRequest,
    manager: JobManagerDep,
    context: ProjectContextDep,
) -> SimulationTools:
    geometry_tools = GeometryTools(
        job_manager=manager,
        project_id=request.project_id,
    )
    return SimulationTools(geometry=geometry_tools, project_context=context, proposal_scope=request.chat_id)


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    manager: JobManagerDep,
    context: ProjectContextDep,
) -> ChatResponse:
    try:
        prompt = _prompt(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tools = _simulation_tools(request, manager, context)
    agent = build_simulation_agent(config=_llm_config(), simulation_tools=tools)
    try:
        response = await agent.run(prompt)
        if request.chat_id:
            store = _workspace()
            store.append(request.project_id, request.chat_id, "user", request.message)
            store.append(request.project_id, request.chat_id, "assistant", response.text or "")
        return ChatResponse(
            message=response.text or "",
            submitted_job_ids=[UUID(job_id) for job_id in tools.submitted_job_ids],
        )
    except Exception as exc:
        logger.exception("Simulation agent request failed")
        raise HTTPException(
            status_code=502,
            detail="Simulation agent request failed",
        ) from exc
    finally:
        await agent.close()


def sse_event(event: str, data: dict) -> str:
    """Encode one SSE event."""
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest,
    manager: JobManagerDep,
    context: ProjectContextDep,
) -> StreamingResponse:
    """Stream agent text and submitted job IDs."""
    try:
        prompt = _prompt(request)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    tools = _simulation_tools(request, manager, context)
    agent = build_simulation_agent(config=_llm_config(), simulation_tools=tools)

    async def generate() -> AsyncIterator[str]:
        reported_jobs: set[str] = set()
        try:
            yield sse_event("status", {"message": "Analyzing request"})
            stream = agent.run(prompt, stream=True)
            async for update in stream:
                if update.text:
                    yield sse_event("delta", {"text": update.text})
                new_jobs = [
                    job_id
                    for job_id in tools.submitted_job_ids
                    if job_id not in reported_jobs
                ]
                if new_jobs:
                    reported_jobs.update(new_jobs)
                    yield sse_event("jobs", {"job_ids": new_jobs})

            final_response = await stream.get_final_response()
            remaining_jobs = [
                job_id
                for job_id in tools.submitted_job_ids
                if job_id not in reported_jobs
            ]
            if remaining_jobs:
                reported_jobs.update(remaining_jobs)
                yield sse_event("jobs", {"job_ids": remaining_jobs})

            if request.chat_id:
                store = _workspace()
                store.append(request.project_id, request.chat_id, "user", request.message)
                store.append(request.project_id, request.chat_id, "assistant", final_response.text or "")

            yield sse_event(
                "done",
                {
                    "message": final_response.text or "",
                    "submitted_job_ids": tools.submitted_job_ids,
                },
            )
        except Exception:
            logger.exception("Streaming simulation agent failed")
            yield sse_event("error", {"message": "Simulation agent request failed"})
        finally:
            await agent.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
