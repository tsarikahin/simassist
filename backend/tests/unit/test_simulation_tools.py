import json
from unittest.mock import Mock

from simassist.agents.tools.simulation_tools import SimulationTools


def test_geometry_capabilities():
    tools = SimulationTools(geometry=Mock())

    result = json.loads(tools.list_geometry_capabilities())

    assert "cylinder" in result["supported"]
    assert result["supported"]["cylinder"] == [
        "radius",
        "height",
    ]


def test_create_geometry_submits_job():
    geometry = Mock()
    geometry.create_geometry.return_value = {
        "ok": True,
        "job_id": "job-123",
        "status": "queued",
    }

    tools = SimulationTools(geometry=geometry)

    result = json.loads(
        tools.create_geometry(
            name="Test Cylinder",
            primitive="cylinder",
            parameters={
                "radius": 10,
                "height": 50,
            },
        )
    )

    assert result["ok"] is True
    assert tools.submitted_job_ids == ["job-123"]

    specification = geometry.create_geometry.call_args.args[0]
    assert specification["units"] == "mm"
    assert specification["definition"]["primitive"] == ("cylinder")


def test_invalid_geometry_not_submitted():
    geometry = Mock()
    tools = SimulationTools(geometry=geometry)

    result = json.loads(
        tools.create_geometry(
            name="Invalid Cylinder",
            primitive="cylinder",
            parameters={"radius": -10, "height": 50},
        )
    )

    assert result["ok"] is False
    geometry.create_geometry.assert_not_called()


def test_missing_parameter_rejected():
    geometry = Mock()
    tools = SimulationTools(geometry=geometry)

    result = json.loads(
        tools.create_geometry(
            name="Invalid Cylinder",
            primitive="cylinder",
            parameters={"radius": 10},
        )
    )

    assert result["ok"] is False
    geometry.create_geometry.assert_not_called()
