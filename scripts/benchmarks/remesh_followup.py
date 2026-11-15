"""Live local-model regression for conversational mesh edits, in isolated projects."""

import argparse
import asyncio
import json
from pathlib import Path
from time import perf_counter
from uuid import UUID, uuid4

from simassist.agents.context import resolve_context
from simassist.agents.orchestrator import compose
from simassist.agents.simulation_agent import build_simulation_agent
from simassist.agents.tools.geometry import GeometryTools
from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.conversations.context_service import ConversationContextService
from simassist.jobs.manager import JobManager
from simassist.llm.config import LLMConfig
from simassist.projects.context import ProjectContextRepository
from simassist.projects.remesh_proposals import RemeshProposalStore
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker

ROOT = Path(__file__).resolve().parents[2]
CREATE = (
    "Create a new 2D annulus with inner radius 1 mm and outer radius 2 mm, "
    "then generate a triangular mesh with sizes 0.05–0.1 mm."
)


def fixture(root):
    worker = SimulationWorker(root)
    manager = JobManager(worker.repository)
    context = ProjectContextRepository(root / "jobs.db", worker.repository)
    store = WorkspaceRepository(root / "jobs.db")
    project = UUID(store.new_project()["id"])
    chat = UUID(store.new_chat(project)["id"])
    services = SimulationTools(GeometryTools(manager, project), context, chat)
    result = json.loads(
        services.create_boolean_geometry_and_mesh(
            name="annulus",
            operation="cut",
            operands=[
                {"primitive": "disk", "parameters": {"radius": 2}},
                {"primitive": "disk", "parameters": {"radius": 1}},
            ],
            units="mm",
            dimension=2,
            min_size=0.05,
            max_size=0.1,
            element_family="triangular",
        )
    )
    assert result["ok"]
    while worker.process_next():
        pass
    jobs = manager.list_by_project(project)
    assert len(jobs) == 2 and all(job.status == "completed" for job in jobs)
    geometry = next(job for job in jobs if job.type == "geometry.create")
    mesh = next(job for job in jobs if job.type == "mesh.generate")
    context.set_active_geometry(project, geometry.id)
    context.set_selected_mesh(project, geometry.id, mesh.id)
    store.append(project, chat, "user", CREATE)
    store.append(
        project,
        chat,
        "assistant",
        "Created and verified the requested annulus and triangular mesh at 0.05–0.1 mm.",
    )
    return worker, manager, context, store, project, chat, geometry, mesh


async def turn(config, manager, context, store, project, chat, message):
    request_id = uuid4()
    store.begin_turn(project, chat, request_id, message)
    services = SimulationTools(GeometryTools(manager, project), context, chat)
    composition = compose(
        message, resolve_context(project, chat, store, context, []), services
    )
    service = ConversationContextService(store)
    assembled = service.build(
        project, chat, message, composition.instructions, composition.schemas
    )
    agent = build_simulation_agent(config, services, composition)
    start = perf_counter()
    try:
        stream = agent.run(
            assembled.messages,
            stream=True,
            options={"max_tokens": service.budget.response, "temperature": 0},
        )

        async def consume():
            async for _ in stream:
                pass
            return await stream.get_final_response()

        response = await asyncio.wait_for(consume(), timeout=120)
        store.finish_turn(
            request_id, "completed", response.text or "", services.submitted_job_ids
        )
        return {
            "message": message,
            "modules": composition.modules,
            "reasons": composition.routing.reasons,
            "tools_invoked": composition.invoked,
            "submitted_job_ids": services.submitted_job_ids,
            "response": response.text,
            "latency_ms": (perf_counter() - start) * 1000,
            "usage": dict(response.usage_details) if response.usage_details else None,
        }
    except Exception:
        store.finish_turn(request_id, "failed", None, services.submitted_job_ids)
        raise
    finally:
        await agent.close()


async def run(args):
    config = LLMConfig(provider="lm_studio", model=args.model, endpoint=args.endpoint)
    root = ROOT / ".benchmarks" / f"remesh-followup-{uuid4().hex}"
    cases = [
        ("exact", "Make it finer.", "Use 0.025–0.05 mm.", 0.025, 0.05),
        (
            "resolution",
            "The triangles look chunky. I'd like better resolution.",
            "Use 0.025–0.05 mm.",
            0.025,
            0.05,
        ),
        (
            "density",
            "Can you back off the density? This is more detail than I need.",
            "Use 0.1–0.2 mm.",
            0.1,
            0.2,
        ),
        ("recover_false_claim", None, "Use 0.025–0.05 mm.", 0.025, 0.05),
    ]
    rows = []
    for name, change, sizes, minimum, maximum in cases:
        worker, manager, context, store, project, chat, geometry, original = fixture(
            root / name
        )
        row = {"case": name, "turns": []}
        if change:
            first = await turn(config, manager, context, store, project, chat, change)
            row["turns"].append(first)
            row["clarification_created"] = bool(
                RemeshProposalStore(context.db_path).get(chat)
            )
            row["no_premature_job"] = len(manager.list_by_project(project)) == 2
            row["clarification_visible"] = bool(first["response"].strip())
        else:
            store.append(project, chat, "user", "Make it finer.")
            store.append(
                project,
                chat,
                "assistant",
                "There is no pending proposal. Please supply min/max sizes.",
            )
            store.append(project, chat, "user", sizes)
            store.append(
                project,
                chat,
                "assistant",
                "Remeshing is not available in this project's capabilities.",
            )
        second = await turn(config, manager, context, store, project, chat, sizes)
        row["turns"].append(second)
        while worker.process_next():
            pass
        jobs = manager.list_by_project(project)
        new_jobs = [job for job in jobs if job.id not in {geometry.id, original.id}]
        row["new_jobs"] = len(new_jobs)
        row["completed"] = all(job.status == "completed" for job in jobs)
        row["same_geometry"] = all(
            job.type == "mesh.generate"
            and job.input.get("geometry_artifact_id") == geometry.result["artifact_id"]
            for job in new_jobs
        )
        row["size_bounds_correct"] = bool(
            len(new_jobs) == 1
            and new_jobs[0].input["settings"]["min_size"] == minimum
            and new_jobs[0].input["settings"]["max_size"] == maximum
        )
        row["original_nodes"] = original.result["metadata"]["node_count"]
        row["new_nodes"] = (
            new_jobs[0].result["metadata"]["node_count"]
            if len(new_jobs) == 1 and new_jobs[0].result
            else None
        )
        row["passed"] = bool(
            row.get("no_premature_job", True)
            and row.get("clarification_visible", True)
            and row["new_jobs"] == 1
            and row["completed"]
            and row["same_geometry"]
            and row["size_bounds_correct"]
        )
        rows.append(row)
        print(json.dumps(row), flush=True)
    result = {
        "model": args.model,
        "endpoint": args.endpoint,
        "temperature": 0,
        "streaming": True,
        "response_reserve_tokens": ConversationContextService(None).budget.response,
        "method": "Fresh isolated verified annulus per case; real local MAF model rounds and worker. No production projects touched. Creation fixture is deterministic, all edit turns use the LLM.",
        "cases": rows,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
    }
    Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    if result["passed"] != result["total"]:
        raise SystemExit("Live follow-up regression failed; see report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="spark-x2.6-4b")
    parser.add_argument("--endpoint", default="http://127.0.0.1:1235/v1")
    parser.add_argument("--output", default="docs/benchmarks/remesh-followup.json")
    asyncio.run(run(parser.parse_args()))
