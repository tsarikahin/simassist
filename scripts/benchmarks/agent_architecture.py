"""Reproduce Phase 11.18B.5 footprint, setup, routing and optional live evaluation.

Run with the backend Python environment. --live uses only the local configured
model and creates isolated projects under .benchmarks; never production data.
Token estimates use the existing UTF-8 bytes/3 + framing heuristic. Setup excludes
provider inference. Live latency includes MAF tool rounds, excludes worker drain.
"""

import argparse
import asyncio
import hashlib
import json
import platform
import statistics
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from agent_framework import Agent, tool
from simassist.agents.context import RoutingContext, resolve_context
from simassist.agents.orchestrator import ToolTelemetry, compose
from simassist.agents.simulation_agent import build_simulation_agent
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.conversations.budget import estimate
from simassist.conversations.context_service import ConversationContextService
from simassist.files.inspect_cad import inspect_step
from simassist.files.repository import FileRepository
from simassist.jobs.manager import JobManager
from simassist.llm.config import LLMConfig
from simassist.llm.factory import create_chat_client
from simassist.projects.context import ProjectContextRepository
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures"
LEGACY = (FIXTURES / "agent_monolithic_instructions.txt").read_text(encoding="utf-8")
SCHEMAS = json.loads((FIXTURES / "agent_monolithic_schemas.json").read_text())
CASES = json.loads((FIXTURES / "agent_routing.json").read_text())
LEGACY_NAMES = [schema["function"]["name"] for schema in SCHEMAS]
CONFIG = LLMConfig(
    provider="lm_studio", model="spark-x2.6-4b", endpoint="http://127.0.0.1:1235/v1"
)


def routing_context(values):
    values = dict(values)
    for index, name in enumerate(("geometry_job_id", "selected_mesh_job_id"), 2):
        if values.get(name):
            values[name] = UUID(int=index)
    return RoutingContext(project_id=UUID(int=1), **values)


def footprint(instructions, schemas):
    serialized = json.dumps(schemas)
    return {
        "instruction_bytes": len(instructions.encode()),
        "schema_bytes": len(serialized.encode()),
        "instruction_estimated_tokens": estimate(instructions),
        "schema_estimated_tokens": estimate(serialized),
        "total_estimated_tokens": estimate(instructions) + estimate(serialized),
        "tools": len(schemas),
    }


def latency(samples):
    result = {"samples": len(samples), "median_ms": statistics.median(samples)}
    if len(samples) >= 30:
        result["p95_ms"] = sorted(samples)[int(0.95 * (len(samples) - 1))]
    return result


async def offline(samples):
    rows = []
    true_positive = false_positive = false_negative = fallbacks = 0
    baseline_tp = baseline_fp = baseline_fn = 0
    route_times = []
    baseline_domains = {"geometry", "meshing", "cad_inspection", "workspace"}
    for case in CASES:
        context = routing_context(case["context"])
        services = SimulationTools(GeometryTools(None, context.project_id))
        start = perf_counter()
        composition = compose(case["message"], context, services)
        route_times.append((perf_counter() - start) * 1000)
        actual = set(composition.routing.domains)
        expected = set(case["domains"])
        true_positive += len(actual & expected)
        false_positive += len(actual - expected)
        false_negative += len(expected - actual)
        baseline_tp += len(baseline_domains & expected)
        baseline_fp += len(baseline_domains - expected)
        baseline_fn += len(expected - baseline_domains)
        fallbacks += composition.routing.fallback
        names = {fn.__name__ for fn in composition.tools}
        rows.append(
            {
                "message": case["message"],
                "domains": composition.routing.domains,
                "modules": composition.modules,
                "fallback": composition.routing.fallback,
                "exact_domain_match": actual == expected,
                "missing_required_tools": sorted(set(case["required_tools"]) - names),
                "baseline_missing_required_tools": sorted(
                    set(case["required_tools"]) - set(LEGACY_NAMES)
                ),
                "modular": footprint(composition.instructions, composition.schemas),
            }
        )
    # Identical six representative workloads, both configurations in alternating
    # order to reduce warm-up/order bias. No provider requests during setup.
    setup = {"monolithic": [], "modular": []}
    workload = [CASES[i] for i in (0, 6, 16, 13, 28, 30)]
    for sample in range(samples + 1):
        for case in workload:
            context = routing_context(case["context"])
            services = SimulationTools(GeometryTools(None, context.project_id))
            for mode in (
                ("monolithic", "modular") if sample % 2 else ("modular", "monolithic")
            ):
                start = perf_counter()
                if mode == "modular":
                    selected = compose(case["message"], context, services)
                    agent = build_simulation_agent(CONFIG, services, selected)
                else:
                    agent = Agent(
                        client=create_chat_client(CONFIG),
                        instructions=LEGACY,
                        tools=[getattr(services, name) for name in LEGACY_NAMES],
                    )
                    [
                        tool(getattr(services, name)).to_json_schema_spec()
                        for name in LEGACY_NAMES
                    ]
                elapsed = (perf_counter() - start) * 1000
                if sample:
                    setup[mode].append(elapsed)
                await agent.close()
    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "maf": version("agent-framework-core"),
            "model": CONFIG.model,
        },
        "method": "Offline estimates, no inference. Setup includes routing/composition, schema generation, client and Agent construction; validated DB context resolution is covered by live setup.",
        "baseline": footprint(LEGACY, SCHEMAS),
        "modular_mean": {
            key: statistics.mean(row["modular"][key] for row in rows)
            for key in rows[0]["modular"]
        },
        "routing": {
            "cases": len(rows),
            "exact_matches": sum(row["exact_domain_match"] for row in rows),
            "micro_precision": true_positive / (true_positive + false_positive),
            "micro_recall": true_positive / (true_positive + false_negative),
            "fallback_rate": fallbacks / len(rows),
            "missing_required_tools": sum(
                bool(row["missing_required_tools"]) for row in rows
            ),
            "baseline_static_availability_precision": baseline_tp
            / (baseline_tp + baseline_fp),
            "baseline_static_availability_recall": baseline_tp
            / (baseline_tp + baseline_fn),
            "note": "Baseline is static capability availability, not an LLM intent classifier. Selection guidance is new, persistent selection tools remain unavailable.",
            "composition_latency": latency(route_times),
        },
        "setup_latency": {mode: latency(values) for mode, values in setup.items()},
        "cases": rows,
    }


def live_fixture(root):
    worker = SimulationWorker(root)
    store = WorkspaceRepository(root / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    manager = JobManager(worker.repository)
    context = ProjectContextRepository(root / "jobs.db", worker.repository)
    geometry, mesh = manager.submit_geometry_mesh(
        project,
        {
            "name": "Benchmark square",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "square",
                "parameters": {"size": 4},
            },
        },
        {
            "dimension": 2,
            "min_size": 0.2,
            "max_size": 0.5,
            "element_family": "triangular",
        },
    )
    worker.process_next()
    worker.process_next()
    context.set_active_geometry(project, geometry.id)
    context.set_selected_mesh(project, geometry.id, mesh.id)
    source = worker.artifact_store.resolve_path(
        UUID(manager.get(geometry.id).result["artifact_id"])
    )
    files = FileRepository(root)
    data = source.read_bytes()
    file_id = files.reserve(project, "benchmark.step", len(data))
    destination = files.path(project, file_id)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    item = files.commit(
        project,
        file_id,
        len(data),
        hashlib.sha256(data).hexdigest(),
        inspect_step(destination),
    )
    services = SimulationTools(
        GeometryTools(manager, project), context, proposal_scope=chat
    )
    return worker, store, project, chat, manager, context, services, item


async def live(repeats):
    root = ROOT / ".benchmarks" / f"agent-live-{uuid4().hex}"
    root.mkdir(parents=True)
    rows = []
    tasks = [
        ("geometry", "Create a 2D disk of radius 2 mm.", ["create_geometry"], 1),
        (
            "meshing",
            "Generate a triangular mesh for the active geometry, min size 0.2 mm, max size 0.5 mm.",
            ["generate_mesh"],
            1,
        ),
        (
            "inspection",
            "Inspect attached STEP file {file_id} and report its dimension and face count.",
            ["inspect_uploaded_file"],
            0,
        ),
        (
            "confirmation",
            "Yes, keep the same sizes for the pending quadrilateral remesh. Confirm it.",
            ["confirm_remesh"],
            1,
        ),
        (
            "mixed",
            "Create a disk of radius 2 mm and mesh it with triangular elements, min size 0.2 mm, max size 0.5 mm.",
            ["create_geometry_and_mesh"],
            2,
        ),
        (
            "negative",
            "Do not create geometry or mesh anything; report current active geometry job status.",
            ["get_active_geometry"],
            0,
        ),
    ]
    for repeat in range(repeats):
        for index, (name, prompt, required, expected_jobs) in enumerate(tasks):
            modes = (
                ("monolithic", "modular")
                if (repeat + index) % 2
                else ("modular", "monolithic")
            )
            for mode in modes:
                worker, store, project, chat, manager, context, services, item = (
                    live_fixture(root / f"{repeat}-{name}-{mode}")
                )
                if name == "confirmation":
                    services.generate_mesh(element_family="quadrilateral")
                prompt_text = prompt.format(file_id=item["file_id"])
                attachments = [item] if name == "inspection" else []
                current = prompt_text
                if attachments:
                    current += "\nUntrusted attachment display metadata: " + json.dumps(
                        [
                            {
                                key: item[key]
                                for key in (
                                    "file_id",
                                    "filename",
                                    "format",
                                    "size_bytes",
                                )
                            }
                        ]
                    )
                start = perf_counter()
                snapshot = resolve_context(project, chat, store, context, attachments)
                composition = compose(prompt_text, snapshot, services)
                if mode == "monolithic":
                    composition.instructions = LEGACY
                    composition.tools = [
                        getattr(services, tool_name) for tool_name in LEGACY_NAMES
                    ]
                    composition.schemas = SCHEMAS
                    agent = Agent(
                        client=create_chat_client(CONFIG),
                        instructions=LEGACY,
                        tools=composition.tools,
                        middleware=[ToolTelemetry(composition)],
                    )
                else:
                    agent = build_simulation_agent(CONFIG, services, composition)
                assembled = ConversationContextService(store).build(
                    project,
                    chat,
                    current,
                    composition.instructions,
                    composition.schemas,
                )
                setup_ms = (perf_counter() - start) * 1000
                existing = {str(job.id) for job in manager.list_by_project(project)}
                error = None
                usage = None
                try:
                    response = await asyncio.wait_for(
                        agent.run(
                            assembled.messages,
                            options={"max_tokens": 768, "temperature": 0},
                        ),
                        timeout=120,
                    )
                    usage = (
                        dict(response.usage_details) if response.usage_details else None
                    )
                except Exception as exc:  # noqa: BLE001 - benchmark records provider failures without retry
                    error = type(exc).__name__
                finally:
                    elapsed = (perf_counter() - start) * 1000
                    await agent.close()
                while worker.process_next():
                    pass
                jobs = [
                    job
                    for job in manager.list_by_project(project)
                    if str(job.id) not in existing
                ]
                row = {
                    "workload": name,
                    "repeat": repeat,
                    "mode": mode,
                    "error": error,
                    "setup_ms": setup_ms,
                    "request_ms": elapsed,
                    "usage": usage,
                    "estimated_input_tokens": assembled.tokens,
                    "tools_invoked": composition.invoked,
                    "expected_tools_observed": set(required)
                    <= set(composition.invoked),
                    "expected_jobs": expected_jobs,
                    "actual_jobs": len(jobs),
                    "completed_jobs": sum(job.status == "completed" for job in jobs),
                    "job_errors": [job.error for job in jobs if job.error],
                    "job_count_correct": len(jobs) == expected_jobs,
                    "duplicate_submissions": max(0, len(jobs) - expected_jobs),
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
    return {
        "model": CONFIG.model,
        "endpoint": CONFIG.endpoint,
        "temperature": 0,
        "max_output_tokens": 768,
        "method": "Local provider, fresh isolated project/chat per case/mode, same verified square/mesh and STEP; full MAF tool loop, then worker verification. No automated reroutes/retries. Small mixed workload; no p95 reported below 30 requests per mode.",
        "results": rows,
        "latency": {
            mode: latency([row["request_ms"] for row in rows if row["mode"] == mode])
            for mode in ("monolithic", "modular")
        },
    }


async def main(args):
    result = await offline(args.samples)
    if args.live:
        result["live"] = await live(args.live_repeats)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: value
                for key, value in result.items()
                if key not in {"cases", "live"}
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=30)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--live-repeats", type=int, default=1)
    parser.add_argument("--output", default="docs/benchmarks/agent-1118b5.json")
    asyncio.run(main(parser.parse_args()))
