from uuid import uuid4

import pytest
from simassist.jobs.models import Job, JobStatus, JobType
from simassist.jobs.repository import JobRepository


@pytest.fixture
def repository(tmp_path):
    return JobRepository(tmp_path / "jobs.db")


def test_submit_and_get(repository):
    job = Job(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
        input={"name": "Test Geometry"},
    )

    repository.submit(job)
    loaded = repository.get(job.id)

    assert loaded.id == job.id
    assert loaded.status == JobStatus.QUEUED
    assert loaded.input == job.input


def test_claim_next(repository):
    job = Job(
        project_id=uuid4(),
        type=JobType.MESH_GENERATE,
    )
    repository.submit(job)

    claimed = repository.claim_next()

    assert claimed is not None
    assert claimed.id == job.id
    assert claimed.status == JobStatus.RUNNING
    assert claimed.started_at is not None

    # The same job cannot be claimed twice.
    assert repository.claim_next() is None


def test_complete_job(repository):
    job = Job(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
    )
    repository.submit(job)
    repository.claim_next()

    completed = repository.complete(
        job.id,
        result={"artifact_id": str(uuid4())},
    )

    assert completed.status == JobStatus.COMPLETED
    assert completed.finished_at is not None
    assert completed.result is not None

    assert repository.get(job.id).status == JobStatus.COMPLETED


def test_fail_job(repository):
    job = Job(
        project_id=uuid4(),
        type=JobType.SIMULATION_RUN,
    )
    repository.submit(job)
    repository.claim_next()

    failed = repository.fail(job.id, "Solver convergence failure")

    assert failed.status == JobStatus.FAILED
    assert failed.error == "Solver convergence failure"


def test_invalid_transition(repository):
    job = Job(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
    )
    repository.submit(job)

    with pytest.raises(ValueError):
        repository.complete(job.id, result={})


def test_persistence_after_reopen(tmp_path):
    db_path = tmp_path / "jobs.db"
    first = JobRepository(db_path)

    job = Job(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
    )
    first.submit(job)

    second = JobRepository(db_path)

    assert second.get(job.id).id == job.id
