"""Request composition and metadata; execution stays in the existing chat lifecycle."""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from time import perf_counter
from uuid import uuid4

from agent_framework import FunctionMiddleware, tool
from pydantic import BaseModel

from simassist.conversations.budget import estimate

from .context import RoutingContext, context_metadata
from .registry import REGISTRY, AgentTool, ModuleRegistry, instructions
from .router import RoutingDecision, canonical_domain, route
from .tools.simulation_tools import SimulationTools

logger = logging.getLogger(__name__)


@dataclass
class AgentComposition:
    instructions: str
    tools: list[AgentTool]
    schemas: list[dict]
    modules: tuple[str, ...]
    routing: RoutingDecision
    estimates: dict[str, int]
    setup_ms: float
    invoked: list[str] = field(default_factory=list)
    route_misses: int = 0
    request_id: str | None = None

    def request_capability(self, domain: str) -> str:
        """Report a missing capability and ask the user to clarify; never execute or replay actions."""
        self.route_misses += 1
        canonical = canonical_domain(domain)
        supported = canonical in REGISTRY.modules
        loaded = canonical in self.modules
        logger.info(
            "agent_route_miss supported=%s selected_modules=%s", supported, self.modules
        )
        return json.dumps(
            {
                "ok": loaded,
                "clarification_required": not loaded,
                "supported_domain": supported,
                "selected_domain": loaded,
                "automatic_retries": 0,
                "message": (
                    "This domain is already loaded. Use its exposed tools for the current request. "
                    "Do not repeat submitted actions."
                    if loaded
                    else "This domain is supported but not loaded for this turn. Ask which operation "
                    "the user intends next. Do not repeat submitted actions."
                    if supported
                    else "No domain matches this label. That alone does not establish that an operation "
                    "is unsupported. Ask a targeted clarification using the known capability limits."
                ),
            }
        )


def _tool_arguments_preview(arguments: object) -> str:
    if isinstance(arguments, BaseModel):
        arguments = arguments.model_dump(mode="json")
    preview = json.dumps(
        arguments, default=str, ensure_ascii=True, separators=(",", ":")
    )
    return preview if len(preview) <= 500 else preview[:497] + "..."


class ToolTelemetry(FunctionMiddleware):
    def __init__(self, composition: AgentComposition | None = None):
        self.composition = composition

    async def process(self, context, call_next):
        name = context.function.name
        call_id = uuid4().hex
        request_id = self.composition.request_id if self.composition else None
        if self.composition:
            self.composition.invoked.append(name)
        started = perf_counter()
        logger.info(
            "agent_tool_start request=%s call=%s tool=%s arguments=%s",
            request_id,
            call_id,
            name,
            _tool_arguments_preview(getattr(context, "arguments", {})),
        )
        status, error_type = "completed", None
        try:
            await call_next()
        except asyncio.CancelledError:
            status, error_type = "cancelled", "CancelledError"
            raise
        except Exception as exc:
            status, error_type = "failed", type(exc).__name__
            raise
        finally:
            logger.info(
                "agent_tool_end request=%s call=%s tool=%s status=%s duration_ms=%.1f error_type=%s",
                request_id,
                call_id,
                name,
                status,
                (perf_counter() - started) * 1000,
                error_type,
            )


def compose(
    message: str,
    context: RoutingContext,
    services: SimulationTools,
    registry: ModuleRegistry = REGISTRY,
) -> AgentComposition:
    start = perf_counter()
    decision = route(message, context)
    modules = registry.resolve(decision.domains)
    core = instructions("core_instructions.md")
    fragments = "\n\n".join(instructions(m.instructions_resource) for m in modules)
    routing_note = (
        "\nRouting needs clarification. Ask which operation is intended before mutating anything."
        if decision.clarification_required
        else ""
    )
    system = (
        core
        + "\n\n"
        + fragments
        + "\nBackend routing context: "
        + context_metadata(context)
        + routing_note
    )
    result = AgentComposition(
        instructions=system,
        tools=registry.bind(modules, services),
        schemas=[],
        modules=tuple(m.name for m in modules),
        routing=decision,
        estimates={},
        setup_ms=0,
    )
    if any(fn.__name__ == "request_capability" for fn in result.tools):
        raise ValueError("Conflicting agent tool name: request_capability")
    result.tools.append(result.request_capability)
    result.schemas = [tool(fn).to_json_schema_spec() for fn in result.tools]
    result.estimates = {
        "core_tokens": estimate(core),
        "domain_tokens": estimate(fragments),
        "instruction_tokens": estimate(system),
        "schema_tokens": estimate(json.dumps(result.schemas)),
    }
    result.setup_ms = (perf_counter() - start) * 1000
    return result
