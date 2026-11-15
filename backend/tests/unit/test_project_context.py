from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from simassist.jobs.models import JobStatus, JobType
from simassist.projects.context import ProjectContextRepository


def test_active_geometry_survives_restart(tmp_path):
    db_path = tmp_path / "jobs.db"
    project_id = uuid4()
    geometry_job_id = uuid4()
    artifact_id = uuid4()

    jobs = Mock()
    jobs.get.return_value = SimpleNamespace(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.COMPLETED,
        result={"artifact_id": str(artifact_id)},
    )

    first = ProjectContextRepository(db_path, jobs)

    selected = first.set_active_geometry(
        project_id,
        geometry_job_id,
    )

    assert selected.active_geometry_job_id == geometry_job_id
    assert selected.active_geometry_artifact_id == artifact_id

    # Simulate a new backend process using the same DB.
    second = ProjectContextRepository(db_path, jobs)
    restored = second.get(project_id)

    assert restored.active_geometry_job_id == geometry_job_id
    assert restored.active_geometry_artifact_id == artifact_id


def test_other_project_geometry_is_rejected(tmp_path):
    jobs = Mock()
    jobs.get.return_value = SimpleNamespace(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.COMPLETED,
        result={"artifact_id": str(uuid4())},
    )

    repository = ProjectContextRepository(
        tmp_path / "jobs.db",
        jobs,
    )

    with pytest.raises(ValueError, match="different project"):
        repository.set_active_geometry(
            uuid4(),
            uuid4(),
        )


def test_incomplete_geometry_is_rejected(tmp_path):
    project_id = uuid4()
    jobs = Mock()
    jobs.get.return_value = SimpleNamespace(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.RUNNING,
        result=None,
    )

    repository = ProjectContextRepository(
        tmp_path / "jobs.db",
        jobs,
    )

    with pytest.raises(ValueError, match="completed"):
        repository.set_active_geometry(
            project_id,
            uuid4(),
        )


def test_clear_does_not_delete_jobs(tmp_path):
    db_path = tmp_path / "jobs.db"
    project_id = uuid4()

    jobs = Mock()
    jobs.get.return_value = SimpleNamespace(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        status=JobStatus.COMPLETED,
        result={"artifact_id": str(uuid4())},
    )

    repository = ProjectContextRepository(db_path, jobs)
    repository.set_active_geometry(project_id, uuid4())

    cleared = repository.clear_active_geometry(project_id)

    assert cleared.active_geometry_job_id is None
    assert cleared.active_geometry_artifact_id is None
    jobs.get.assert_called_once()
