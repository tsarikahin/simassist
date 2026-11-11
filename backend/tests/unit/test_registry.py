import pytest
from simassist.core.capabilities import (
    Capability,
    EngineDescriptor,
)
from simassist.core.registry import EngineRegistry


def test_engine_registration():
    registry = EngineRegistry()

    geometry_engine = object()
    meshing_engine = object()

    registry.register(
        key="gmsh.geometry",
        engine=geometry_engine,
        descriptor=EngineDescriptor(
            name="gmsh.geometry",
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
            capabilities={Capability.MESH_GENERATE},
        ),
    )

    assert registry.get("gmsh.geometry") is geometry_engine
    assert registry.get("gmsh.meshing") is meshing_engine

    assert registry.find_by_capability(Capability.MESH_GENERATE) == ["gmsh.meshing"]


def test_duplicate_engine_registration():
    registry = EngineRegistry()

    descriptor = EngineDescriptor(
        name="gmsh.geometry",
        capabilities={Capability.GEOMETRY_CREATE},
    )

    registry.register("gmsh.geometry", object(), descriptor)

    with pytest.raises(ValueError):
        registry.register("gmsh.geometry", object(), descriptor)
