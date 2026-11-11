from uuid import UUID

from fastapi import APIRouter

from simassist.api.dependencies import (
    ArtifactStoreDep,
    get_data_root,
)
from simassist.core.capabilities import EngineDescriptor
from simassist.services.factory import create_simulation_service

router = APIRouter(
    prefix="/api/engines",
    tags=["Engines"],
)


@router.get("", response_model=list[EngineDescriptor])
def list_engines(
    project_id: UUID,
    store: ArtifactStoreDep,
):
    service = create_simulation_service(
        project_id=project_id,
        workspace=get_data_root() / "workspaces" / str(project_id),
        artifact_store=store,
    )

    return service.registry.list_engines()
