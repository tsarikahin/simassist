from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from simassist.api.dependencies import JobManagerDep
from simassist.jobs.models import Job, JobStatus

router = APIRouter(prefix="/api", tags=["Job Events"])

TERMINAL_STATUSES = {
    JobStatus.COMPLETED,
    JobStatus.FAILED,
    JobStatus.CANCELLED,
}


def get_project_job(
    manager: JobManagerDep,
    project_id: UUID,
    job_id: UUID,
) -> Job:
    """Load a job and verify that it belongs to the project."""
    try:
        job = manager.get(job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        ) from exc

    if job.project_id != project_id:
        raise HTTPException(
            status_code=404,
            detail="Job not found",
        )

    return job


def encode_event(event: str, job: Job) -> str:
    return f"event: {event}\ndata: {job.model_dump_json()}\n\n"


@router.get("/projects/{project_id}/jobs/{job_id}/events")
async def stream_job_events(
    project_id: UUID,
    job_id: UUID,
    request: Request,
    manager: JobManagerDep,
) -> StreamingResponse:
    """Stream job state changes until the job reaches a terminal state."""

    # Return HTTP 404 before opening the event stream.
    get_project_job(manager, project_id, job_id)

    async def generate() -> AsyncIterator[str]:
        last_status: JobStatus | None = None
        last_payload: str | None = None

        while True:
            if await request.is_disconnected():
                return

            try:
                job = manager.get(job_id)
            except KeyError:
                return

            # Avoid sending duplicate snapshots.
            payload = job.model_dump_json()

            if job.status != last_status or payload != last_payload:
                yield encode_event("job", job)

                last_status = job.status
                last_payload = payload

            if job.status in TERMINAL_STATUSES:
                yield encode_event("end", job)
                return

            await asyncio.sleep(0.75)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )
