from uuid import uuid4

from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobStatus, JobType
from simassist.workers.runner import SimulationWorker


def test_worker_creates_geometry(tmp_path):
    worker = SimulationWorker(data_root=tmp_path)

    manager = JobManager(worker.repository)
    project_id = uuid4()

    job = manager.submit(
        project_id=project_id,
        job_type=JobType.GEOMETRY_CREATE,
        payload={
            "name": "Worker Test Geometry",
            "definition": {
                "source": "primitive",
                "primitive": "box",
                "parameters": {
                    "length": 100,
                    "width": 20,
                    "height": 10,
                },
            },
        },
    )

    result = worker.process_next()

    assert result is not None
    assert result.id == job.id
    assert result.status == JobStatus.COMPLETED
    assert result.result is not None

    artifact_id = result.result["artifact_id"]

    from uuid import UUID

    path = worker.artifact_store.resolve_path(UUID(artifact_id))

    assert path.exists()
    assert path.suffix == ".step"

    assert worker.repository.get(job.id).status == JobStatus.COMPLETED
