from uuid import uuid4

from simassist.jobs.manager import JobManager
from simassist.jobs.models import JobStatus, JobType
from simassist.jobs.repository import JobRepository


def test_job_manager_submit(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    manager = JobManager(repository)

    project_id = uuid4()

    job = manager.submit(
        project_id=project_id,
        job_type=JobType.GEOMETRY_CREATE,
        payload={
            "name": "Test Geometry",
            "definition": {
                "source": "primitive",
                "primitive": "sphere",
                "parameters": {"radius": 10},
            },
        },
    )

    assert job.status == JobStatus.QUEUED
    assert manager.get(job.id).id == job.id
    assert len(manager.list_by_project(project_id)) == 1
