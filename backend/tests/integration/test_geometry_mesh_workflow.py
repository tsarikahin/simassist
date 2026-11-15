from uuid import uuid4

from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobStatus, JobType
from simassist.workers.runner import SimulationWorker


def test_geometry_mesh_workflow(tmp_path):
    worker = SimulationWorker(data_root=tmp_path)
    manager = JobManager(worker.repository)
    project_id = uuid4()

    geometry_job, mesh_job = manager.submit_geometry_mesh(
        project_id=project_id,
        geometry_payload={
            "name": "Workflow Test Box",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "box",
                "parameters": {
                    "length": 20,
                    "width": 10,
                    "height": 5,
                },
            },
        },
        mesh_settings={
            "dimension": 3,
            "min_size": 2.0,
            "max_size": 5.0,
        },
    )

    assert mesh_job.depends_on == geometry_job.id

    # First worker iteration must execute geometry.
    first = worker.process_next()

    assert first is not None
    assert first.id == geometry_job.id
    assert first.status == JobStatus.COMPLETED

    # Mesh must remain queued until the dependency finishes.
    assert worker.repository.get(mesh_job.id).status == JobStatus.QUEUED

    # Second iteration automatically executes meshing.
    second = worker.process_next()

    assert second is not None
    assert second.id == mesh_job.id
    assert second.type == JobType.MESH_GENERATE
    assert second.status == JobStatus.COMPLETED

    assert second.result["geometry_artifact_id"] == first.result["artifact_id"]

    assert second.result["metadata"]["node_count"] > 0
    assert second.result["metadata"]["element_count"] > 0

    from uuid import UUID

    mesh_path = worker.artifact_store.resolve_path(UUID(second.result["artifact_id"]))

    assert mesh_path.exists()
    assert mesh_path.suffix == ".msh"


def test_failed_dependency_prevents_meshing(tmp_path):
    worker = SimulationWorker(data_root=tmp_path)
    manager = JobManager(worker.repository)
    project_id = uuid4()

    geometry_job, mesh_job = manager.submit_geometry_mesh(
        project_id=project_id,
        geometry_payload={
            "name": "Invalid Geometry",
            "units": "mm",
            "definition": {
                "source": "primitive",
                "primitive": "box",
                "parameters": {
                    "length": 10,
                    "width": 5,
                },
            },
        },
        mesh_settings={
            "dimension": 3,
            "min_size": 1.0,
            "max_size": 3.0,
        },
    )

    first = worker.process_next()

    assert first is not None
    assert first.id == geometry_job.id
    assert first.status == JobStatus.FAILED

    # Scheduler propagates the dependency failure.
    assert worker.process_next() is None

    dependent = worker.repository.get(mesh_job.id)

    assert dependent.status == JobStatus.FAILED
    assert "Dependency" in dependent.error
