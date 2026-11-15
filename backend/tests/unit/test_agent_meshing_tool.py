import json
from unittest.mock import Mock
from uuid import uuid4

from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.jobs.models import Job, JobType


def test_generate_mesh_from_completed_geometry():
    project_id = uuid4()
    geometry_job_id = uuid4()
    geometry_artifact_id = uuid4()

    geometry = Mock()
    geometry.project_id = project_id

    geometry.get_job_status.return_value = {
        "ok": True,
        "job_id": str(geometry_job_id),
        "job_type": JobType.GEOMETRY_CREATE.value,
        "status": "completed",
        "result": {"artifact_id": str(geometry_artifact_id)},
    }

    expected_job = Job(
        project_id=project_id,
        type=JobType.MESH_GENERATE,
        input={},
    )

    geometry.job_manager.submit.return_value = expected_job

    tools = SimulationTools(geometry)

    response = json.loads(
        tools.generate_mesh(
            geometry_job_id=str(geometry_job_id),
            dimension=3,
            min_size=1.0,
            max_size=5.0,
        )
    )

    assert response["ok"] is True
    assert response["job_id"] == str(expected_job.id)

    kwargs = geometry.job_manager.submit.call_args.kwargs

    assert kwargs["project_id"] == project_id
    assert kwargs["job_type"] == JobType.MESH_GENERATE
    assert kwargs["payload"]["geometry_artifact_id"] == str(geometry_artifact_id)
    assert kwargs["payload"]["settings"]["dimension"] == 3


def test_generate_mesh_requires_completed_geometry():
    geometry = Mock()

    geometry.get_job_status.return_value = {
        "ok": True,
        "job_type": JobType.GEOMETRY_CREATE.value,
        "status": "running",
        "result": None,
    }

    tools = SimulationTools(geometry)

    result = json.loads(
        tools.generate_mesh(
            geometry_job_id=str(uuid4()),
        )
    )

    assert result["ok"] is False
    assert result["status"] == "running"

    geometry.job_manager.submit.assert_not_called()


def test_generate_mesh_rejects_invalid_sizes():
    geometry = Mock()
    tools = SimulationTools(geometry)

    result = json.loads(
        tools.generate_mesh(
            geometry_job_id=str(uuid4()),
            min_size=10.0,
            max_size=2.0,
        )
    )

    assert result["ok"] is False
    geometry.job_manager.submit.assert_not_called()


def test_generate_mesh_rejects_invalid_job_id():
    geometry = Mock()
    tools = SimulationTools(geometry)

    result = json.loads(
        tools.generate_mesh(
            geometry_job_id="not-a-uuid",
        )
    )

    assert result["ok"] is False
    geometry.get_job_status.assert_not_called()
