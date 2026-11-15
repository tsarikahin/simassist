from __future__ import annotations

import argparse
import logging
import time
from pathlib import Path
from uuid import UUID

from simassist.core.models.artifact import ArtifactCreate, ArtifactType
from simassist.core.models.geometry import CADImportGeometry, GeometrySpec
from simassist.core.models.mesh import MeshRequest
from simassist.files.repository import FileRepository
from simassist.jobs.models import Job, JobStatus, JobType
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

    def _resolve_mesh_request(self, job: Job) -> MeshRequest:
        """Resolve a mesh input from a completed geometry job.

        Also supports legacy mesh jobs with geometry_artifact_id.
        """

        if "geometry_artifact_id" in job.input:
            return MeshRequest.model_validate(job.input)

        geometry_job_id = UUID(str(job.input["geometry_job_id"]))

        if job.depends_on != geometry_job_id:
            raise ValueError("Mesh dependency does not match geometry job ID")

        geometry_job = self.repository.get(geometry_job_id)

        if geometry_job.project_id != job.project_id:
            raise ValueError("Geometry dependency belongs to another project")

        if geometry_job.type != JobType.GEOMETRY_CREATE:
            raise ValueError("Mesh dependency must be a geometry job")

        if geometry_job.status != JobStatus.COMPLETED:
            raise ValueError("Geometry dependency is not completed")

        if not geometry_job.result:
            raise ValueError("Geometry dependency has no result")

        artifact_id = geometry_job.result.get("artifact_id")

        if not artifact_id:
            raise ValueError("Geometry dependency has no artifact")

        return MeshRequest.model_validate(
            {
                "geometry_artifact_id": artifact_id,
                "settings": job.input["settings"],
            }
        )

    def process_next(self) -> Job | None:
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
                uploaded = None
                if (
                    isinstance(spec.definition, CADImportGeometry)
                    and spec.definition.file_id
                ):
                    files = FileRepository(self.data_root)
                    uploaded = files.get(job.project_id, spec.definition.file_id)
                    original = self.artifact_store.save(
                        ArtifactCreate(
                            project_id=job.project_id,
                            type=ArtifactType.OTHER,
                            source_path=files.resolve(
                                job.project_id, spec.definition.file_id
                            ),
                        )
                    )
                    spec.definition = CADImportGeometry(artifact_id=original.id)

                result = service.create_geometry(spec)

                preview_service = GmshPreviewService(
                    workspace=workspace / "previews",
                    artifact_store=self.artifact_store,
                    project_id=job.project_id,
                )

                preview_artifact_id = preview_service.generate(result.artifact_id)

                result_payload = result.model_dump(mode="json")

                result_payload["preview_artifact_id"] = str(preview_artifact_id)
                if uploaded:
                    result_payload.update(
                        source_file_id=uploaded["file_id"],
                        source_content_hash=uploaded["content_hash"],
                        units="mm",
                    )

            elif job.type == JobType.MESH_GENERATE:
                request = self._resolve_mesh_request(job)

                result = service.generate_mesh(request)

                result_payload = result.model_dump(mode="json")

            else:
                raise NotImplementedError(f"Unsupported job type: {job.type}")

            # Verify real artifacts before declaring completion.
            #
            # The mesh verifier expects a MeshRequest containing
            # geometry_artifact_id. For dependent jobs we supply
            # the resolved request to the verifier without changing
            # the original persisted job input.
            verification_job = job

            if job.type == JobType.MESH_GENERATE:
                verification_job = job.model_copy(
                    update={"input": request.model_dump(mode="json")}
                )

            self.verifier.verify(
                job=verification_job,
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
