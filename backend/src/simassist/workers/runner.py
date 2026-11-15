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
from simassist.simulation.visualization.gmsh_preview import (
    GmshPreviewService,
)
from simassist.storage.local import LocalArtifactStore
from simassist.verification.service import VerificationService

logger = logging.getLogger(__name__)


class SimulationWorker:
    """Execute queued simulation jobs in a separate process."""

    def __init__(
        self,
        data_root: Path,
        poll_interval: float = 1.0,
    ) -> None:
        self.data_root = data_root.resolve()
        self.data_root.mkdir(parents=True, exist_ok=True)

        self.repository = JobRepository(self.data_root / "jobs.db")

        self.artifact_store = LocalArtifactStore(self.data_root / "artifacts")

        self.verifier = VerificationService(artifact_store=self.artifact_store)

        self.poll_interval = poll_interval

    def process_next(self) -> Job | None:
        """Claim, execute, verify, and finalize one queued job."""

        job = self.repository.claim_next()

        if job is None:
            return None

        logger.info(
            "Processing job %s (%s)",
            job.id,
            job.type,
        )

        try:
            workspace = self.data_root / "workspaces" / str(job.project_id)

            service = create_simulation_service(
                project_id=job.project_id,
                workspace=workspace,
                artifact_store=self.artifact_store,
            )

            if job.type == JobType.GEOMETRY_CREATE:
                spec = GeometrySpec.model_validate(job.input)

                result = service.create_geometry(spec)

                preview_service = GmshPreviewService(
                    workspace=workspace / "previews",
                    artifact_store=self.artifact_store,
                    project_id=job.project_id,
                )

                preview_artifact_id = preview_service.generate(result.artifact_id)

                result_payload = result.model_dump(mode="json")

                result_payload["preview_artifact_id"] = str(preview_artifact_id)

            elif job.type == JobType.MESH_GENERATE:
                request = MeshRequest.model_validate(job.input)

                result = service.generate_mesh(request)

                result_payload = result.model_dump(mode="json")

            else:
                raise NotImplementedError(f"Unsupported job type: {job.type}")

            # Verify artifacts before completing the job.
            self.verifier.verify(
                job=job,
                result=result_payload,
            )

        except Exception as exc:
            logger.exception(
                "Execution or verification failed for job %s",
                job.id,
            )

            return self.repository.fail(
                job.id,
                error=str(exc),
            )

        # Finalization is outside the execution/verification
        # exception handler. If database completion fails,
        # we must not blindly attempt another state transition.
        updated = self.repository.complete(
            job.id,
            result=result_payload,
        )

        logger.info(
            "Completed and verified job %s",
            job.id,
        )

        return updated

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
