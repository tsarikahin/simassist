"""Exercise reset previews on an isolated checkout without executing deletion."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows reset script")
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "reset_runtime.ps1"
UUID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, root / "scripts" / SCRIPT.name)
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    return root


def preview(root, process_query="throw 'process inspection unavailable'"):
    # Mock the read-only process query, keeping these tests independent of CIM ACLs.
    command = (
        f"function Get-CimInstance {{ {process_query} }}; "
        "& './scripts/reset_runtime.ps1'"
    )
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            command,
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    ).stdout


def snapshot(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_preview_protects_tracked_unknown_and_gitkeep_files(checkout):
    runtime = checkout / "data"
    artifact = runtime / "artifacts" / "files" / UUID / UUID / "geometry.step"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"tracked fixture")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "-f", str(artifact)],
        check=True,
        capture_output=True,
    )
    jobs = runtime / "jobs.db"
    jobs.write_bytes(b"runtime database")
    (runtime / ".gitkeep").touch()
    (runtime / "notes.txt").write_text("unrelated")
    upload = checkout / "backend" / "data" / "uploads" / UUID / f"{UUID}.step"
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"uploaded STEP")
    before = snapshot(checkout)

    output = preview(checkout)

    assert f"DELETE FILE {jobs}" in output
    assert f"DELETE FILE {upload}" in output
    assert f"PRESERVE {artifact}" in output
    assert f"PRESERVE {runtime / '.gitkeep'}" in output
    assert f"PRESERVE {runtime / 'notes.txt'}" in output
    assert "Cannot verify that API and worker are stopped" in output
    assert "Dry run only" in output
    assert snapshot(checkout) == before


@pytest.mark.parametrize(
    ("query", "message"),
    [
        (
            "[pscustomobject]@{Name='python.exe'; ProcessId=123; CommandLine=$null}",
            "Stop API, worker, and Python/uv/ASGI hosts",
        ),
        (
            "[pscustomobject]@{Name='System'; ProcessId=4; CommandLine=$null}",
            "Process check passed",
        ),
    ],
)
def test_preview_reports_process_readiness(checkout, query, message):
    output = preview(checkout, query)
    assert message in output
    assert "Dry run only" in output


def test_preview_is_repeatable_after_empty_reset(checkout):
    (checkout / "data").mkdir()
    (checkout / "backend" / "data").mkdir(parents=True)
    before = snapshot(checkout)
    assert "Planned files: 0" in preview(checkout)
    assert "Planned files: 0" in preview(checkout)
    assert snapshot(checkout) == before
