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


def test_selected_mesh_is_validated_persisted_and_distinct_from_latest(tmp_path):
    import json

    from simassist.agents.tools.geometry import GeometryTools
    from simassist.agents.tools.simulation_tools import SimulationTools
    from simassist.jobs.manager import JobManager
    from simassist.jobs.repository import JobRepository

    jobs = JobRepository(tmp_path / "jobs.db")
    manager = JobManager(jobs)
    project = uuid4()
    geometry = manager.submit(project, JobType.GEOMETRY_CREATE, {})
    jobs.claim_next()
    geometry_artifact = uuid4()
    jobs.complete(geometry.id, {"artifact_id": str(geometry_artifact)})
    meshes = []
    for _ in range(2):
        mesh = manager.submit(
            project,
            JobType.MESH_GENERATE,
            {"geometry_artifact_id": str(geometry_artifact)},
        )
        jobs.claim_next()
        jobs.complete(
            mesh.id,
            {
                "artifact_id": str(uuid4()),
                "geometry_artifact_id": str(geometry_artifact),
                "metadata": {"node_count": 20, "element_count": 30},
            },
        )
        meshes.append(mesh.id)
    context = ProjectContextRepository(tmp_path / "jobs.db", jobs)
    context.set_active_geometry(project, geometry.id)
    context.set_selected_mesh(project, geometry.id, meshes[0])
    restored = ProjectContextRepository(tmp_path / "jobs.db", jobs)
    assert restored.get(project).selected_mesh_job_id == meshes[0]
    info = json.loads(
        SimulationTools(
            GeometryTools(manager, project), restored
        ).get_active_mesh_info()
    )
    assert info["selected_mesh"]["mesh_job_id"] == str(meshes[0])
    assert info["latest_completed_mesh"]["mesh_job_id"] == str(meshes[1])
    with pytest.raises(ValueError):
        context.set_selected_mesh(uuid4(), geometry.id, meshes[0])
    queued = manager.submit(project, JobType.MESH_GENERATE, {})
    with pytest.raises(ValueError):
        context.set_selected_mesh(project, geometry.id, queued.id)
    with pytest.raises(ValueError):
        context.set_selected_mesh(project, uuid4(), meshes[0])
    jobs.claim_next()
    jobs.fail(queued.id, "Fixture failure")
    with pytest.raises(ValueError):
        context.set_selected_mesh(project, geometry.id, queued.id)
    foreign = manager.submit(project, JobType.MESH_GENERATE, {})
    jobs.claim_next()
    jobs.complete(
        foreign.id, {"artifact_id": str(uuid4()), "geometry_artifact_id": str(uuid4())}
    )
    with pytest.raises(ValueError, match="revision"):
        context.set_selected_mesh(project, geometry.id, foreign.id)
    context.set_active_geometry(project, geometry.id)
    assert context.get(project).selected_mesh_job_id == meshes[0]
    context.clear_active_geometry(project)
    assert context.get(project).selected_mesh_job_id is None
