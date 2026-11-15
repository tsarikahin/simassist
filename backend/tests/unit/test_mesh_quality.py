from types import SimpleNamespace

import numpy as np
import pytest
from simassist.simulation.meshing.quality import analyze_mesh


def _mesh(points, family, cells):
    return SimpleNamespace(
        points=np.asarray(points, dtype=float),
        cells=[SimpleNamespace(type=family, data=np.asarray(cells, dtype=int))],
    )


def test_line_lengths_and_degenerate():
    report = analyze_mesh(
        _mesh([[0, 0, 0], [1, 0, 0], [1, 0, 0]], "line", [[0, 1], [1, 2]])
    )
    assert report["dimension"] == 1
    assert report["segment_length"]["mean"] == 0.5
    assert report["degenerate_count"] == 1
    assert report["quality"] is None


def test_equilateral_triangle_has_unit_quality():
    report = analyze_mesh(
        _mesh(
            [[0, 0, 0], [1, 0, 0], [0.5, np.sqrt(3) / 2, 0]],
            "triangle",
            [[0, 1, 2]],
        )
    )
    assert report["quality"]["min"] == pytest.approx(1)
    assert report["low_quality_count"] == 0


def test_square_quad_has_unit_quality():
    report = analyze_mesh(
        _mesh(
            [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
            "quad",
            [[0, 1, 2, 3]],
        )
    )
    assert report["dimension"] == 2
    assert report["quality"]["min"] == pytest.approx(1)
    assert report["element_families"] == {"quadrilateral": 1}


def test_regular_tetrahedron_has_unit_quality():
    report = analyze_mesh(
        _mesh(
            [
                [0, 0, 0],
                [1, 0, 0],
                [0.5, np.sqrt(3) / 2, 0],
                [0.5, np.sqrt(3) / 6, np.sqrt(2 / 3)],
            ],
            "tetra",
            [[0, 1, 2, 3]],
        )
    )
    assert report["dimension"] == 3
    assert report["quality"]["min"] == pytest.approx(1, abs=1e-5)


def test_tetra_ignores_boundary_triangles():
    mesh = _mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], "tetra", [[0, 1, 2, 3]])
    mesh.cells.append(SimpleNamespace(type="triangle", data=np.array([[0, 1, 2]])))
    report = analyze_mesh(mesh)
    assert report["analyzed_element_count"] == 1
    assert report["dimension"] == 3


def test_degenerate_triangle_is_reported():
    report = analyze_mesh(
        _mesh([[0, 0, 0], [1, 0, 0], [2, 0, 0]], "triangle", [[0, 1, 2]])
    )
    assert report["quality"]["min"] == 0
    assert report["degenerate_count"] == 1
    assert report["low_quality_count"] == 1


def test_invalid_connectivity_is_rejected():
    with pytest.raises(ValueError, match="connectivity"):
        analyze_mesh(_mesh([[0, 0, 0], [1, 0, 0], [0, 1, 0]], "triangle", [[0, 1, 5]]))
