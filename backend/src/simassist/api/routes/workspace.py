"""Workspace APIs: independent projects and durable conversation sessions."""

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from simassist.api.dependencies import get_data_root
from simassist.projects.workspace import WorkspaceRepository

router = APIRouter(prefix="/api/workspace", tags=["Workspace"])


class NameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)


def repo():
    return WorkspaceRepository(get_data_root() / "jobs.db")


@router.get("/projects")
def projects():
    return repo().projects()


@router.post("/projects")
def create_project(body: NameRequest):
    return repo().new_project(body.name.strip())


@router.post("/projects/legacy")
def import_legacy():
    """Make historical demo jobs accessible without migrating or modifying them."""
    return repo().import_legacy()


@router.patch("/projects/{project_id}")
def rename_project(project_id: UUID, body: NameRequest):
    try:
        repo().rename_project(project_id, body.name.strip())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/projects/{project_id}/chats")
def chats(project_id: UUID):
    return repo().chats(project_id)


@router.post("/projects/{project_id}/chats")
def new_chat(project_id: UUID):
    return repo().new_chat(project_id)


@router.get("/projects/{project_id}/chats/{chat_id}/messages")
def messages(project_id: UUID, chat_id: UUID):
    try:
        return repo().messages(project_id, chat_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/projects/{project_id}/chats/{chat_id}")
def rename_chat(project_id: UUID, chat_id: UUID, body: NameRequest):
    try:
        repo().rename_chat(project_id, chat_id, body.name.strip())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.delete("/projects/{project_id}/chats/{chat_id}")
def delete_chat(project_id: UUID, chat_id: UUID):
    try:
        repo().delete_chat(project_id, chat_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"ok": True}
