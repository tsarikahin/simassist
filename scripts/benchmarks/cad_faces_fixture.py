"""Disposable CAD-only HTTP fixture for browser selection checks (no FEM mesh)."""

import argparse
import os
from pathlib import Path
from uuid import UUID

import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--port", type=int, default=8003)
args = parser.parse_args()
root = args.root.resolve()
if not root.is_relative_to(Path.cwd() / ".benchmarks"):
    parser.error("Fixture root must be within the workspace .benchmarks directory")
root.mkdir(parents=True, exist_ok=True)
os.chdir(root)

from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobType
from simassist.projects.context import ProjectContextRepository
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker

worker = SimulationWorker(root / "data")
workspace = WorkspaceRepository(root / "data/jobs.db")
project = workspace.new_project("CAD picking test")
project_id = UUID(project["id"])
manager = JobManager(worker.repository)
geometries = []
definitions = [
    (
        "Picking block",
        {
            "source": "primitive",
            "primitive": "box",
            "parameters": {"length": 20, "width": 20, "height": 20},
        },
    ),
    (
        "Planar plate",
        {
            "source": "primitive",
            "primitive": "rectangle",
            "parameters": {"width": 20, "height": 20},
        },
    ),
    (
        "Block with hole",
        {
            "source": "csg",
            "operation": "cut",
            "operands": [
                {
                    "primitive": "box",
                    "parameters": {"length": 20, "width": 20, "height": 20},
                },
                {
                    "primitive": "cylinder",
                    "parameters": {"radius": 4, "height": 20},
                    "origin": {"x": 10, "y": 10, "z": 0},
                },
            ],
        },
    ),
]
for name, definition in definitions:
    job = manager.submit(
        project_id,
        JobType.GEOMETRY_CREATE,
        {"name": name, "units": "mm", "definition": definition},
    )
    completed = worker.process_next()
    assert completed.status.value == "completed", completed.error
    geometries.append({"name": name, "job_id": str(job.id), **completed.result})
ProjectContextRepository(root / "data/jobs.db", worker.repository).set_active_geometry(
    project_id, UUID(geometries[0]["job_id"])
)

from fastapi.middleware.cors import CORSMiddleware
from simassist.api.routes import workspace as workspace_routes
from simassist.main import app

for middleware in app.user_middleware:
    if middleware.cls is CORSMiddleware:
        middleware.kwargs["allow_origins"] += ["http://127.0.0.1:4176"]
workspace.open_default_project = lambda: project
workspace_routes.repo = lambda: workspace


@app.get("/benchmark/config")
def configuration():
    return {"project": project, "geometries": geometries}


uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
