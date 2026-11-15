from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from simassist.agents.context import resolve_context
from simassist.agents.orchestrator import compose
from simassist.agents.simulation_agent import build_simulation_agent
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.api.dependencies import JobManagerDep, ProjectContextDep, get_data_root
from simassist.conversations.context_service import ConversationContextService
from simassist.files.repository import FileRepository
from simassist.llm.config import LLMConfig
from simassist.projects.workspace import WorkspaceRepository

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Chat"])


class AttachmentReference(BaseModel):
    file_id: UUID


class ChatRequest(BaseModel):
    project_id: UUID
    chat_id: UUID | None = None
    request_id: UUID = Field(default_factory=uuid4)
    message: str = Field(min_length=1, max_length=10000)
    attachments: list[AttachmentReference] = Field(default_factory=list)

    @field_validator("attachments")
    @classmethod
    def validate_attachments(cls, value):
        if len(value) > int(os.getenv("SIMASSIST_MAX_CHAT_ATTACHMENTS", "4")):
            raise ValueError("Too many attachments in one message")
        if len({item.file_id for item in value}) != len(value):
            raise ValueError("Duplicate attachment references")
        return value


class ChatResponse(BaseModel):
    message: str
    submitted_job_ids: list[UUID] = Field(default_factory=list)


def _workspace() -> WorkspaceRepository:
    return WorkspaceRepository(get_data_root() / "jobs.db")


def _llm_config() -> LLMConfig:
    return LLMConfig(
        provider="lm_studio",
        model=os.getenv("SIMASSIST_MODEL", "spark-x2.6-4b"),
        endpoint=os.getenv("SIMASSIST_LLM_ENDPOINT", "http://127.0.0.1:1235/v1"),
    )


def _simulation_tools(request, manager, context):
    return SimulationTools(
        geometry=GeometryTools(job_manager=manager, project_id=request.project_id),
        project_context=context,
        proposal_scope=request.chat_id,
    )


class ChatExecution:
    """Shared sync/SSE lifecycle. Never replay raw tool traces or failed turns."""

    def __init__(self, request, manager, context):
        self.started = perf_counter()
        self.composition = None
        self.request = request
        self.store = _workspace()
        self.tools = _simulation_tools(request, manager, context)
        self.agent = None
        self.accepted = False
        self.finished = False
        self.cached = None
        try:
            attachments = []
            if request.attachments:
                files = FileRepository(self.store.db_path.parent)
                for reference in request.attachments:
                    item = files.get(request.project_id, reference.file_id)
                    attachments.append(
                        {
                            key: item[key]
                            for key in ("file_id", "filename", "format", "size_bytes")
                        }
                    )
            current = request.message
            if attachments:
                current += (
                    "\nUntrusted attachment display metadata; inspect files using tools: "
                    + json.dumps(attachments)
                )
            if request.chat_id:
                self.cached = self.store.begin_turn(
                    request.project_id,
                    request.chat_id,
                    request.request_id,
                    request.message,
                    [item.file_id for item in request.attachments],
                )
                self.accepted = self.cached is None
            if self.cached:
                return
            service = ConversationContextService(self.store)
            self.budget = service.budget
            snapshot = resolve_context(
                request.project_id, request.chat_id, self.store, context, attachments
            )
            self.composition = compose(request.message, snapshot, self.tools)
            assembled = service.build(
                request.project_id,
                request.chat_id,
                current,
                self.composition.instructions,
                self.composition.schemas,
            )
            self.messages = assembled.messages
            config = _llm_config()
            logger.info(
                "chat_context project=%s chat=%s request=%s provider=%s model=%s "
                "turns=%s watermark=%s estimated_tokens=%s budget=%s summary=%s",
                request.project_id,
                request.chat_id,
                request.request_id,
                config.provider,
                config.model,
                assembled.turns,
                assembled.watermark,
                assembled.tokens,
                self.budget.available,
                assembled.summary_status,
            )
            self.agent = build_simulation_agent(
                config=config, simulation_tools=self.tools, composition=self.composition
            )
            self.composition.estimates["conversation_tokens"] = (
                assembled.tokens
                - self.composition.estimates["instruction_tokens"]
                - self.composition.estimates["schema_tokens"]
            )
            self.composition.estimates["total_input_tokens"] = assembled.tokens
            logger.info(
                "agent_composition %s",
                json.dumps(
                    {
                        "project_id": str(request.project_id),
                        "chat_id": str(request.chat_id),
                        "request_id": str(request.request_id),
                        "modules": self.composition.modules,
                        "reasons": self.composition.routing.reasons,
                        "fallback": self.composition.routing.fallback,
                        "tools_available": [
                            fn.__name__ for fn in self.composition.tools
                        ],
                        "estimated_tokens": self.composition.estimates,
                        "routing_composition_ms": self.composition.setup_ms,
                        "setup_ms": (perf_counter() - self.started) * 1000,
                    }
                ),
            )
        except KeyError as exc:
            self.finish("failed")
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            self.finish("failed")
            raise HTTPException(
                422 if self.accepted or not request.chat_id else 409, str(exc)
            ) from exc
        except Exception as exc:
            self.finish("failed")
            logger.error(
                "Chat initialization failed request=%s type=%s",
                request.request_id,
                type(exc).__name__,
            )
            raise HTTPException(502, "Simulation agent initialization failed") from exc

    def result(self):
        return ChatResponse(
            message=self.cached["response"],
            submitted_job_ids=json.loads(self.cached["job_ids"]),
        )

    def finish(self, status, text=None, usage=None):
        if self.finished:
            return
        if self.accepted:
            self.store.finish_turn(
                self.request.request_id, status, text, self.tools.submitted_job_ids
            )
        self.finished = True
        if self.composition:
            logger.info(
                "agent_completion %s",
                json.dumps(
                    {
                        "project_id": str(self.request.project_id),
                        "chat_id": str(self.request.chat_id),
                        "request_id": str(self.request.request_id),
                        "status": status,
                        "modules": self.composition.modules,
                        "tools_invoked": self.composition.invoked,
                        "route_misses": self.composition.route_misses,
                        "automatic_retries": 0,
                        "completion_ms": (perf_counter() - self.started) * 1000,
                        "provider_usage": dict(usage) if usage else None,
                    }
                ),
            )
        logger.info(
            "chat_turn project=%s chat=%s request=%s status=%s submitted_jobs=%s",
            self.request.project_id,
            self.request.chat_id,
            self.request.request_id,
            status,
            self.tools.submitted_job_ids,
        )

    async def close(self):
        if self.agent:
            await self.agent.close()

    @property
    def options(self):
        return {"max_tokens": self.budget.response}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest, manager: JobManagerDep, context: ProjectContextDep
) -> ChatResponse:
    execution = ChatExecution(request, manager, context)
    if execution.cached:
        return execution.result()
    try:
        response = await execution.agent.run(
            execution.messages, options=execution.options
        )
        execution.finish(
            "completed", response.text or "", getattr(response, "usage_details", None)
        )
        return ChatResponse(
            message=response.text or "",
            submitted_job_ids=execution.tools.submitted_job_ids,
        )
    except asyncio.CancelledError:
        execution.finish("interrupted")
        raise
    except Exception as exc:
        execution.finish("failed")
        logger.error(
            "Simulation agent failed request=%s type=%s",
            request.request_id,
            type(exc).__name__,
        )
        raise HTTPException(
            502, "Simulation agent request failed; inspect project jobs before retrying"
        ) from exc
    finally:
        await execution.close()


def sse_event(event: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat/stream")
async def stream_chat(
    request: ChatRequest, manager: JobManagerDep, context: ProjectContextDep
) -> StreamingResponse:
    execution = ChatExecution(request, manager, context)

    async def generate() -> AsyncIterator[str]:
        reported_jobs: set[str] = set()
        try:
            if execution.cached:
                result = execution.result()
                yield sse_event("done", result.model_dump(mode="json"))
                return
            yield sse_event("status", {"message": "Analyzing request"})
            stream = execution.agent.run(
                execution.messages, stream=True, options=execution.options
            )
            async for update in stream:
                if update.text:
                    yield sse_event("delta", {"text": update.text})
                new_jobs = [
                    j
                    for j in execution.tools.submitted_job_ids
                    if j not in reported_jobs
                ]
                if new_jobs:
                    reported_jobs.update(new_jobs)
                    yield sse_event("jobs", {"job_ids": new_jobs})
            final = await stream.get_final_response()
            execution.finish(
                "completed", final.text or "", getattr(final, "usage_details", None)
            )
            remaining = [
                j for j in execution.tools.submitted_job_ids if j not in reported_jobs
            ]
            if remaining:
                yield sse_event("jobs", {"job_ids": remaining})
            yield sse_event(
                "done",
                {
                    "message": final.text or "",
                    "submitted_job_ids": execution.tools.submitted_job_ids,
                },
            )
        except (asyncio.CancelledError, GeneratorExit):
            execution.finish("interrupted")
            raise
        except Exception as exc:  # noqa: BLE001 - translate provider failures to SSE
            execution.finish("failed")
            logger.error(
                "Streaming agent failed request=%s type=%s",
                request.request_id,
                type(exc).__name__,
            )
            yield sse_event(
                "error",
                {
                    "message": "Simulation agent request failed; inspect project jobs before retrying",
                    "submitted_job_ids": execution.tools.submitted_job_ids,
                },
            )
        finally:
            execution.finish("interrupted")
            await execution.close()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
