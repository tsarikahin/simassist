"""Isolated HTTP fixture for real browser tests; never opens the user's jobs DB."""

import argparse
import json
import os
import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--baseline", action="store_true")
parser.add_argument("--port", type=int, default=8002)
args = parser.parse_args()
repo_root = Path.cwd()
root = args.root.resolve()
if not root.is_relative_to(repo_root / ".benchmarks"):
    parser.error("Fixture root must be inside this workspace .benchmarks directory")
root.mkdir(parents=True, exist_ok=True)
os.chdir(root)
os.environ["SIMASSIST_DATA_DIR"] = str(root / "data")

from simassist.core.models.artifact import ArtifactCreate, ArtifactType
from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobType
from simassist.projects.context import ProjectContextRepository
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers.runner import SimulationWorker

worker = SimulationWorker(root / "data")
manager = JobManager(worker.repository)
workspace = WorkspaceRepository(root / "data/jobs.db")
config_path = root / "fixture.json"
if config_path.exists():
    fixture = json.loads(config_path.read_text())
else:
    project = workspace.new_project("Viewer benchmark")
    project_id = UUID(project["id"])
    geometry = manager.submit(
        project_id,
        JobType.GEOMETRY_CREATE,
        {
            "name": "120k tet block",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "box",
                "parameters": {"length": 20, "width": 20, "height": 50},
            },
        },
    )
    completed = worker.process_next()
    assert completed.status.value == "completed", completed.error
    context = ProjectContextRepository(root / "data/jobs.db", worker.repository)
    context.set_active_geometry(project_id, geometry.id)
    jobs = []
    for _ in range(2):
        artifact = worker.artifact_store.save(
            ArtifactCreate(
                project_id=project_id,
                type=ArtifactType.MESH,
                source_path=repo_root / ".benchmarks/viewer-1118a/120k-tetra.msh",
                parent_ids=[UUID(completed.result["artifact_id"])],
            )
        )
        job = manager.submit(
            project_id,
            JobType.MESH_GENERATE,
            {
                "geometry_artifact_id": completed.result["artifact_id"],
                "settings": {
                    "dimension": 3,
                    "min_size": 0.5,
                    "max_size": 1.5,
                    "element_family": "tetrahedral",
                },
            },
        )
        worker.repository.claim_next()
        result = {
            "mesh_id": str(job.id),
            "engine": "gmsh",
            "artifact_id": str(artifact.id),
            "geometry_artifact_id": completed.result["artifact_id"],
            "metadata": {
                "node_count": 22491,
                "element_count": 120000,
                "element_types": {"Tetrahedron 4": 120000},
                "volume_element_types": {"Tetrahedron 4": 120000},
            },
        }
        worker.verifier.verify(job, result)
        worker.repository.complete(job.id, result)
        jobs.append(str(job.id))
    fixture = {
        "project": project,
        "geometry_job_id": str(geometry.id),
        "mesh_job_ids": jobs,
        "preview_id": completed.result["preview_artifact_id"],
    }
    config_path.write_text(json.dumps(fixture))

if "additional_geometries" not in fixture:
    fixture["additional_geometries"] = []
    for name, definition, dimension, family in [
        (
            "Preflight 1D line",
            {"source": "primitive", "primitive": "line", "parameters": {"length": 4}},
            1,
            "line",
        ),
        (
            "Preflight 2D annulus",
            {
                "source": "csg",
                "operation": "cut",
                "operands": [
                    {
                        "source": "primitive",
                        "primitive": "disk",
                        "parameters": {"radius": 2},
                    },
                    {
                        "source": "primitive",
                        "primitive": "disk",
                        "parameters": {"radius": 1},
                    },
                ],
            },
            2,
            "triangular",
        ),
    ]:
        geometry, mesh = manager.submit_geometry_mesh(
            UUID(fixture["project"]["id"]),
            {"name": name, "units": "mm", "definition": definition},
            {
                "dimension": dimension,
                "min_size": 0.1,
                "max_size": 0.3,
                "element_family": family,
            },
        )
        for _ in range(2):
            completed = worker.process_next()
            assert completed.status.value == "completed", completed.error
        fixture["additional_geometries"].append(
            {
                "name": name,
                "geometry_job_id": str(geometry.id),
                "mesh_job_id": str(mesh.id),
                "dimension": dimension,
            }
        )
    config_path.write_text(json.dumps(fixture))
ProjectContextRepository(root / "data/jobs.db", worker.repository).set_active_geometry(
    UUID(fixture["project"]["id"]), UUID(fixture["geometry_job_id"])
)

from fastapi.middleware.cors import CORSMiddleware
from simassist.main import app

for middleware in app.user_middleware:
    if middleware.cls is CORSMiddleware:
        middleware.kwargs["allow_origins"] += [
            "http://127.0.0.1:4174",
            "http://127.0.0.1:4175",
        ]
from simassist.api.routes import workspace as workspace_routes

workspace.open_default_project = lambda: fixture["project"]
workspace_routes.repo = lambda: workspace


@app.post("/benchmark/reset-preview-cache")
def reset_preview_cache():
    for job_id in fixture["mesh_job_ids"]:
        job = manager.get(UUID(job_id))
        path = (
            worker.artifact_store.resolve_path(UUID(job.result["artifact_id"])).parent
            / ".simassist-preview-cache"
        )
        assert path.resolve().is_relative_to(root)
        if path.exists():
            for derived in path.glob("v*.json"):
                derived.unlink()
    return {"ok": True}


@app.get("/benchmark/config")
def configuration():
    return fixture


if args.baseline:
    from simassist.api.routes import mesh_previews, mesh_versions

    namespace = runpy.run_path(
        str(repo_root / ".benchmarks/viewer-1118a/legacy_mesh_previews.py")
    )
    legacy = namespace["build_mesh_preview"]

    def legacy_preview(path, artifact):
        preview = legacy(path)
        return SimpleNamespace(
            response=lambda job_id, artifact_id: {
                **preview,
                "mesh_job_id": str(job_id),
                "mesh_artifact_id": str(artifact_id),
            }
        )

    mesh_previews.cached_mesh_preview = legacy_preview
    mesh_versions.cached_mesh_preview = legacy_preview

uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
