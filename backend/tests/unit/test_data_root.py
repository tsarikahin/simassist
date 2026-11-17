"""Runtime root selection must be independent of API/worker launch directory."""

import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from simassist.api import dependencies
from simassist.core import paths
from simassist.files.repository import FileRepository
from simassist.main import app
from simassist.projects.workspace import WorkspaceRepository
from simassist.workers import runner


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path / "checkout"
    (root / "backend").mkdir(parents=True)
    monkeypatch.setattr(paths, "REPOSITORY_ROOT", root)
    monkeypatch.delenv("SIMASSIST_DATA_DIR", raising=False)
    return root


@pytest.mark.parametrize("directory", [".", "backend"])
def test_default_root_is_shared_across_launch_directories(
    checkout, monkeypatch, directory
):
    monkeypatch.chdir(checkout / directory)
    expected = checkout / "data"
    assert dependencies.get_data_root() == expected
    assert not expected.exists()

    worker = runner.SimulationWorker()
    assert worker.data_root == expected
    assert worker.repository.db_path == dependencies.get_job_repository().db_path
    assert worker.artifact_store.root == dependencies.get_artifact_store().root
    assert worker.repository.db_path == expected / "jobs.db"
    assert worker.artifact_store.root == expected / "artifacts"

    context = dependencies.get_project_context_repository(worker.repository)
    workspace = WorkspaceRepository(expected / "jobs.db")
    files = FileRepository(workspace.db_path.parent)
    assert context.db_path == workspace.db_path == files.workspace.db_path
    assert files.root == worker.data_root


@pytest.mark.parametrize("directory", [".", "backend"])
def test_environment_root_is_shared_across_launch_directories(
    checkout, tmp_path, monkeypatch, directory
):
    selected = tmp_path / "selected"
    monkeypatch.setenv("SIMASSIST_DATA_DIR", str(selected))
    monkeypatch.chdir(checkout / directory)
    assert dependencies.get_data_root() == selected
    assert runner.SimulationWorker().data_root == selected
    assert not (checkout / "data").exists()


@pytest.mark.parametrize("configured", ["", "  ", "data", "../data"])
def test_environment_requires_absolute_path(checkout, monkeypatch, configured):
    monkeypatch.setenv("SIMASSIST_DATA_DIR", configured)
    with pytest.raises(ValueError, match="must be an absolute directory path"):
        paths.resolve_data_root()
    assert not (checkout / "data").exists()


@pytest.mark.parametrize("canonical_exists", [False, True])
def test_existing_legacy_store_requires_selection_before_startup(
    checkout, monkeypatch, caplog, canonical_exists
):
    legacy = checkout / "backend" / "data"
    legacy.mkdir()
    legacy_db = legacy / "jobs.db"
    legacy_db.write_bytes(b"legacy sentinel")
    canonical = checkout / "data"
    if canonical_exists:
        canonical.mkdir()
        (canonical / "jobs.db").write_bytes(b"canonical sentinel")
    monkeypatch.chdir(checkout)

    with (
        pytest.raises(ValueError, match="Select a data root explicitly"),
        TestClient(app),
    ):
        pass
    with pytest.raises(ValueError, match="Select a data root explicitly"):
        runner.SimulationWorker()

    assert str(legacy) in caplog.text
    assert str(canonical) in caplog.text
    assert legacy_db.read_bytes() == b"legacy sentinel"
    if canonical_exists:
        assert (canonical / "jobs.db").read_bytes() == b"canonical sentinel"
    else:
        assert not canonical.exists()
    assert list(legacy.iterdir()) == [legacy_db]


@pytest.mark.parametrize("selected", ["data", "backend/data"])
def test_explicit_selection_resolves_legacy_ambiguity(checkout, monkeypatch, selected):
    legacy = checkout / "backend" / "data"
    legacy.mkdir()
    (legacy / "jobs.db").write_bytes(b"legacy sentinel")
    expected = checkout / selected
    monkeypatch.setenv("SIMASSIST_DATA_DIR", str(expected))
    assert paths.resolve_data_root() == expected
    assert paths.resolve_data_root(expected) == expected


@pytest.mark.parametrize("directory", [".", "backend"])
def test_worker_override_precedes_environment_and_preserves_relative_paths(
    checkout, monkeypatch, directory
):
    monkeypatch.chdir(checkout / directory)
    monkeypatch.setenv("SIMASSIST_DATA_DIR", "invalid-relative-setting")
    expected = (checkout / directory / "chosen").resolve()
    assert runner.SimulationWorker(Path("chosen")).data_root == expected


def test_api_and_worker_log_selected_absolute_root(checkout, monkeypatch, caplog):
    selected = checkout / "selected"
    monkeypatch.setenv("SIMASSIST_DATA_DIR", str(selected))
    with caplog.at_level(logging.INFO):
        with TestClient(app):
            pass
        assert not selected.exists()
        runner.SimulationWorker()
    assert f"API runtime data root: {selected}" in caplog.text
    assert f"Worker runtime data root: {selected}" in caplog.text


def test_worker_cli_passes_explicit_override(checkout, monkeypatch):
    monkeypatch.setattr(
        "sys.argv", ["worker", "--data-root", str(checkout / "selected"), "--once"]
    )
    calls = []

    class Worker:
        def __init__(self, data_root):
            calls.append(data_root)

        def process_next(self):
            calls.append("once")

    monkeypatch.setattr(runner, "SimulationWorker", Worker)
    runner.main()
    assert calls == [checkout / "selected", "once"]
