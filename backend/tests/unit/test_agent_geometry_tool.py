from unittest.mock import Mock
from uuid import uuid4

from simassist.agents.tools.geometry import GeometryTools
from simassist.jobs.models import Job, JobType


def test_create_geometry_submits_valid_job():
    project_id = uuid4()
    manager = Mock()

    expected_job = Job(
        project_id=project_id,
        type=JobType.GEOMETRY_CREATE,
        input={},
    )

    manager.submit.return_value = expected_job

    tools = GeometryTools(
        job_manager=manager,
        project_id=project_id,
    )

    result = tools.create_geometry(
        {
            "name": "Cylinder",
            "definition": {
                "source": "primitive",
                "primitive": "cylinder",
                "parameters": {
                    "radius": 10,
                    "height": 50,
                },
            },
        }
    )

    assert result["ok"] is True
    assert result["job_id"] == str(expected_job.id)

    manager.submit.assert_called_once()

    kwargs = manager.submit.call_args.kwargs

    assert kwargs["project_id"] == project_id
    assert kwargs["job_type"] == JobType.GEOMETRY_CREATE
    assert kwargs["payload"]["name"] == "Cylinder"


def test_create_geometry_rejects_invalid_input():
    manager = Mock()

    tools = GeometryTools(
        job_manager=manager,
        project_id=uuid4(),
    )

    result = tools.create_geometry(
        {
            "name": "Invalid",
            "definition": {
                "source": "unsupported_shape",
            },
        }
    )

    assert result["ok"] is False
    manager.submit.assert_not_called()


def test_get_job_status_rejects_other_project():
    manager = Mock()

    job = Job(
        project_id=uuid4(),
        type=JobType.GEOMETRY_CREATE,
        input={},
    )

    manager.get.return_value = job

    tools = GeometryTools(
        job_manager=manager,
        project_id=uuid4(),
    )

    result = tools.get_job_status(str(job.id))

    assert result == {
        "ok": False,
        "error": "Job not found",
    }
