from uuid import uuid4

from fastapi.testclient import TestClient
from simassist.api.dependencies import get_job_repository
from simassist.jobs.repository import JobRepository
from simassist.main import app


def test_create_and_retrieve_geometry_job(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")
    project_id = uuid4()

    app.dependency_overrides[get_job_repository] = lambda: repository

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "project_id": str(project_id),
                    "type": "geometry.create",
                    "input": {
                        "name": "Test Box",
                        "definition": {
                            "source": "primitive",
                            "primitive": "box",
                            "parameters": {
                                "length": 100,
                                "width": 20,
                                "height": 10,
                            },
                        },
                    },
                },
            )

            assert response.status_code == 202
            job = response.json()
            assert job["status"] == "queued"

            job_id = job["id"]

            response = client.get(f"/api/jobs/{job_id}")
            assert response.status_code == 200
            assert response.json()["id"] == job_id

            response = client.get(f"/api/projects/{project_id}/jobs")
            assert response.status_code == 200
            assert len(response.json()) == 1

    finally:
        app.dependency_overrides.clear()


def test_invalid_geometry_job(tmp_path):
    repository = JobRepository(tmp_path / "jobs.db")

    app.dependency_overrides[get_job_repository] = lambda: repository

    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/jobs",
                json={
                    "project_id": str(uuid4()),
                    "type": "geometry.create",
                    "input": {"name": "Invalid"},
                },
            )

            assert response.status_code == 422
            assert repository.claim_next() is None

    finally:
        app.dependency_overrides.clear()
