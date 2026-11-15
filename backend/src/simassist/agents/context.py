"""Read-only routing facts. Dialogue is a hint; services own engineering state."""

import json
from dataclasses import dataclass
from uuid import UUID

from simassist.files.repository import FileRepository
from simassist.jobs.models import JobStatus, JobType
from simassist.projects.context import ProjectContextRepository
from simassist.projects.remesh_proposals import RemeshProposalStore
from simassist.projects.workspace import WorkspaceRepository


@dataclass(frozen=True)
class RoutingContext:
    project_id: UUID
    chat_id: UUID | None = None
    geometry_job_id: UUID | None = None
    selected_mesh_job_id: UUID | None = None
    has_completed_mesh: bool = False
    pending_remesh: bool = False
    attachment_formats: tuple[str, ...] = ()
    recent_attachment_formats: tuple[str, ...] = ()
    recent_intent: str = ""
    issues: tuple[str, ...] = ()


def resolve_context(
    project_id: UUID,
    chat_id: UUID | None,
    store: WorkspaceRepository,
    context: ProjectContextRepository | None,
    attachments: list[dict],
) -> RoutingContext:
    # Applies even to legacy requests without a chat. Deleted projects retain jobs.
    recent = ""
    recent_formats: tuple[str, ...] = ()
    if chat_id:
        previous_user = store.latest_context_user(project_id, chat_id)
        recent = previous_user["content"][:1000] if previous_user else ""
        # Resolve references through project ownership again, rather than routing
        # on a filename pasted in dialogue. Missing uploads are merely stale hints.
        if previous_user:
            references = store.attachment_metadata(previous_user["id"])
            formats = []
            for reference in references:
                try:
                    item = FileRepository(store.db_path.parent).get(
                        project_id, reference["file_id"]
                    )
                    formats.append(item["format"])
                except (KeyError, ValueError):
                    continue
            recent_formats = tuple(formats)
    else:
        store.chats(project_id)
    geometry_id = selected_id = None
    has_mesh = pending = False
    issues: list[str] = []
    if context is not None:
        selected = context.get(project_id)
        repository = context.job_repository
        artifact_id = None
        if selected.active_geometry_job_id:
            try:
                job = repository.get(selected.active_geometry_job_id)
                artifact_id = (job.result or {}).get("artifact_id")
                if (
                    job.project_id != project_id
                    or job.type != JobType.GEOMETRY_CREATE
                    or job.status != JobStatus.COMPLETED
                    or not artifact_id
                    or str(artifact_id) != str(selected.active_geometry_artifact_id)
                    or store.geometry_overrides(project_id)
                    .get(str(job.id), {})
                    .get("deleted", 0)
                ):
                    raise ValueError("Invalid active geometry")
                geometry_id = job.id
            except (KeyError, ValueError):
                artifact_id = None
                issues.append("stale_geometry")
        if artifact_id:
            for job in repository.list_by_project(project_id):
                if (
                    job.type == JobType.MESH_GENERATE
                    and job.status == JobStatus.COMPLETED
                    and str((job.result or {}).get("geometry_artifact_id"))
                    == str(artifact_id)
                ):
                    has_mesh = True
                    if job.id == selected.selected_mesh_job_id:
                        selected_id = job.id
        if selected.selected_mesh_job_id and not selected_id:
            issues.append("stale_mesh")
        # Scope matches SimulationTools, including legacy chatless requests.
        proposal = RemeshProposalStore(context.db_path).get(chat_id or project_id)
        if proposal:
            pending = True  # Stale proposals still route to meshing for rejection/cancellation.
            if proposal.get("geometry_job_id") != str(geometry_id):
                issues.append("stale_proposal")
    return RoutingContext(
        project_id=project_id,
        chat_id=chat_id,
        geometry_job_id=geometry_id,
        selected_mesh_job_id=selected_id,
        has_completed_mesh=has_mesh,
        pending_remesh=pending,
        attachment_formats=tuple(str(item["format"]).lower() for item in attachments),
        recent_attachment_formats=recent_formats,
        recent_intent=recent,
        issues=tuple(issues),
    )


def context_metadata(context: RoutingContext) -> str:
    """Only authoritative IDs/flags, never filenames or historical instructions."""
    return json.dumps(
        {
            "active_geometry_job_id": str(context.geometry_job_id)
            if context.geometry_job_id
            else None,
            "selected_mesh_job_id": str(context.selected_mesh_job_id)
            if context.selected_mesh_job_id
            else None,
            "pending_remesh": context.pending_remesh,
            "issues": context.issues,
        }
    )
