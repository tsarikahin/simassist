"""Request composition and metadata; execution stays in the existing chat lifecycle."""

import json
import logging
from dataclasses import dataclass, field
from time import perf_counter

from agent_framework import FunctionMiddleware, tool

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


class ToolTelemetry(FunctionMiddleware):
    def __init__(self, composition: AgentComposition):
        self.composition = composition

    async def process(self, context, call_next):
        self.composition.invoked.append(context.function.name)
        await call_next()


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
