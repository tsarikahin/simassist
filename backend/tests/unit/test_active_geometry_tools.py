import json
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from simassist.agents.tools.simulation_tools import SimulationTools
from simassist.jobs.models import JobType


def _tools(with_active_geometry: bool = True):
    geometry = Mock()
    geometry.project_id = uuid4()
    geometry_job_id = uuid4()
    artifact_id = uuid4()

    context = Mock()
    context.get.return_value = SimpleNamespace(
        active_geometry_job_id=geometry_job_id if with_active_geometry else None,
        active_geometry_artifact_id=artifact_id if with_active_geometry else None,
    )
    geometry.get_job_status.return_value = {
        "ok": True,
        "job_type": JobType.GEOMETRY_CREATE,
        "status": "completed",
        "result": {"artifact_id": str(artifact_id)},
    }
    geometry.job_manager.submit.return_value = SimpleNamespace(
        id=uuid4(),
        type=JobType.MESH_GENERATE,
        status=SimpleNamespace(value="queued"),
    )
    return SimulationTools(geometry, context), geometry, context


def test_active_geometry_is_returned():
    tools, geometry, context = _tools()
    result = json.loads(tools.get_active_geometry())
    assert result["ok"] is True
    context.get.assert_called_once_with(geometry.project_id)


def test_generate_mesh_uses_selected_geometry():
    tools, geometry, _ = _tools()
    result = json.loads(
        tools.generate_mesh(min_size=1, max_size=3, element_family="tetrahedral")
    )
    assert result["ok"] is True
    assert len(tools.submitted_job_ids) == 1
    kwargs = geometry.job_manager.submit.call_args.kwargs
    assert kwargs["payload"]["settings"]["element_family"] == "tetrahedral"


def test_no_active_geometry_does_not_submit():
    tools, geometry, _ = _tools(with_active_geometry=False)
    result = json.loads(tools.generate_mesh())
    assert result["ok"] is False
    geometry.job_manager.submit.assert_not_called()


def test_hex_does_not_submit_or_resolve_geometry():
    tools, geometry, context = _tools()
    result = json.loads(tools.generate_mesh(element_family="hexahedral"))
    assert result["ok"] is False
    context.get.assert_not_called()
    geometry.job_manager.submit.assert_not_called()
