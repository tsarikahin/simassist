from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path

from simassist.core.models.geometry import GeometrySpec
from simassist.core.models.mesh import MeshRequest
from simassist.jobs.models import Job, JobType
from simassist.jobs.repository import JobRepository
from simassist.services.factory import create_simulation_service
from simassist.storage.local import LocalArtifactStore

logger = logging.getLogger(__name__)


class SimulationWorker:
    """Execute queued simulation jobs in a separate process."""

    def __init__(
        self,
        data_root: Path,
        poll_interval: float = 1.0,
    ):
        self.data_root = data_root.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.repository = JobRepository(self.data_root / "jobs.db")
        self.artifact_store = LocalArtifactStore(self.data_root / "artifacts")
        self.poll_interval = poll_interval

    def process_next(self) -> Job | None:
        job = self.repository.claim_next()

        if job is None:
            return None

        logger.info("Processing job %s (%s)", job.id, job.type)

        try:
            service = create_simulation_service(
                project_id=job.project_id,
                workspace=(self.data_root / "workspaces" / str(job.project_id)),
                artifact_store=self.artifact_store,
            )

            if job.type == JobType.GEOMETRY_CREATE:
                spec = GeometrySpec.model_validate(job.input)
                result = service.create_geometry(spec)

            elif job.type == JobType.MESH_GENERATE:
                request = MeshRequest.model_validate(job.input)
                result = service.generate_mesh(request)

            else:
                raise NotImplementedError(f"Unsupported job type: {job.type}")

            updated = self.repository.complete(
                job.id,
                result=result.model_dump(mode="json"),
            )

            logger.info("Completed job %s", job.id)
            return updated

        except Exception as exc:
            logger.exception("Job %s failed", job.id)

            return self.repository.fail(
                job.id,
                error=str(exc),
            )

    def run_forever(self) -> None:
        logger.info("Simulation worker started")

        while True:
            job = self.process_next()

            if job is None:
                time.sleep(self.poll_interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="SimAssist local simulation worker")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=Path.cwd() / "data",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Process one queued job and exit",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    worker = SimulationWorker(data_root=args.data_root)

    if args.once:
        worker.process_next()
    else:
        worker.run_forever()


if __name__ == "__main__":
    main()
