import json
from unittest.mock import Mock

import pytest
from simassist.agents.tools.simulation_tools import SimulationTools


@pytest.mark.parametrize(
    ("parameters", "expected"),
    [
        (
            {"length": 80, "width": 40, "height": 20},
            {"length": 80, "width": 40, "height": 20},
        ),
        (
            {"dx": 80, "dy": 40, "dz": 20},
            {"length": 80, "width": 40, "height": 20},
        ),
        (
            {"dx": 80, "width": 40, "dz": 20},
            {"length": 80, "width": 40, "height": 20},
        ),
    ],
)
def test_box_parameters_normalized(parameters, expected):
    geometry = Mock()
    geometry.create_geometry.return_value = {
        "ok": True,
        "job_id": "test-job-id",
    }

    tools = SimulationTools(geometry)

    result = json.loads(
        tools.create_geometry(
            name="Test Box",
            primitive="box",
            parameters=parameters,
        )
    )

    assert result["ok"] is True

    submitted = geometry.create_geometry.call_args.args[0]
    assert submitted["definition"]["parameters"] == expected


def test_conflicting_box_parameters_rejected():
    geometry = Mock()
    tools = SimulationTools(geometry)

    result = json.loads(
        tools.create_geometry(
            name="Invalid Box",
            primitive="box",
            parameters={
                "dx": 80,
                "length": 90,
                "width": 40,
                "height": 20,
            },
        )
    )

    assert result["ok"] is False
    geometry.create_geometry.assert_not_called()


def test_invalid_box_dimensions_rejected():
    geometry = Mock()
    tools = SimulationTools(geometry)

    result = json.loads(
        tools.create_geometry(
            name="Invalid Box",
            primitive="box",
            parameters={
                "length": -80,
                "width": 40,
                "height": 20,
            },
        )
    )

    assert result["ok"] is False
    geometry.create_geometry.assert_not_called()
