from pathlib import Path
from uuid import UUID

from simassist.core.capabilities import (
    Capability,
    EngineDescriptor,
)
from simassist.core.registry import EngineRegistry
from simassist.services.simulation import SimulationService
from simassist.simulation.geometry.gmsh_adapter import (
    GmshGeometryAdapter,
)
from simassist.simulation.meshing.gmsh_adapter import (
    GmshMeshingAdapter,
)
from simassist.storage.base import ArtifactStore


def create_simulation_service(
    project_id: UUID,
    workspace: Path,
    artifact_store: ArtifactStore,
) -> SimulationService:
    """Create a project-scoped simulation service."""

    registry = EngineRegistry()

    geometry_engine = GmshGeometryAdapter(
        workspace=workspace / "geometry",
        artifact_store=artifact_store,
        project_id=project_id,
    )

    meshing_engine = GmshMeshingAdapter(
        workspace=workspace / "meshing",
        artifact_store=artifact_store,
        project_id=project_id,
    )

    registry.register(
        key="gmsh.geometry",
        engine=geometry_engine,
        descriptor=EngineDescriptor(
            name="gmsh.geometry",
            description="Gmsh OpenCASCADE geometry engine",
            capabilities={
                Capability.GEOMETRY_CREATE,
                Capability.GEOMETRY_INSPECT,
            },
        ),
    )

    registry.register(
        key="gmsh.meshing",
        engine=meshing_engine,
        descriptor=EngineDescriptor(
            name="gmsh.meshing",
            description="Gmsh finite element meshing engine",
            capabilities={
                Capability.MESH_GENERATE,
            },
        ),
    )

    return SimulationService(registry)
