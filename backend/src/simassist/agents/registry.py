"""Declarative capabilities; no model, runtime, or engineering service ownership."""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Protocol

from .tools.simulation_tools import SimulationTools

AgentTool = Callable[..., str]


class ToolFactory(Protocol):
    def __call__(self, services: SimulationTools) -> Sequence[AgentTool]: ...


def bundle(*names: str) -> ToolFactory:
    def bind(services: SimulationTools) -> Sequence[AgentTool]:
        return tuple(getattr(services, name) for name in names)

    return bind


@lru_cache(maxsize=32)
def instructions(resource: str) -> str:
    return (
        files("simassist.agents").joinpath(resource).read_text(encoding="utf-8").strip()
    )


@dataclass(frozen=True)
class AgentModule:
    name: str
    tool_factory: ToolFactory
    dependencies: tuple[str, ...] = ("workspace",)
    # Bridges become available only when all of these domains were requested.
    include_when: tuple[str, ...] = ()

    @property
    def instructions_resource(self) -> str:
        return f"modules/{self.name}/instructions.md"


class ModuleRegistry:
    def __init__(self, modules: Sequence[AgentModule]):
        self.modules = {module.name: module for module in modules}
        if len(self.modules) != len(modules):
            raise ValueError("Duplicate module name")
        for module in modules:
            for name in (*module.dependencies, *module.include_when):
                if name not in self.modules:
                    raise ValueError(f"Unknown dependency {name} in {module.name}")
        # Validate even unused dependency branches at startup.
        self.resolve(self.modules)

    def resolve(self, domains: Iterable[str]) -> tuple[AgentModule, ...]:
        requested = set(domains)
        if "workspace" in self.modules:
            requested.add("workspace")
        while True:
            expanded = set(requested)
            for name in requested:
                if name not in self.modules:
                    raise ValueError(f"Unknown agent module: {name}")
                expanded.update(self.modules[name].dependencies)
            for module in self.modules.values():
                if module.include_when and set(module.include_when) <= expanded:
                    expanded.add(module.name)
            if expanded == requested:
                break
            requested = expanded
        result: list[AgentModule] = []
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(name: str):
            if name not in self.modules:
                raise ValueError(f"Unknown agent module: {name}")
            if name in visiting:
                raise ValueError(f"Cyclic module dependency: {name}")
            if name in visited:
                return
            visiting.add(name)
            module = self.modules[name]
            for dependency in sorted(module.dependencies):
                visit(dependency)
            visiting.remove(name)
            visited.add(name)
            result.append(module)

        for name in sorted(requested):
            visit(name)
        return tuple(result)

    def bind(
        self, modules: Sequence[AgentModule], services: SimulationTools
    ) -> list[AgentTool]:
        tools: dict[str, AgentTool] = {}
        for module in modules:
            for fn in module.tool_factory(services):
                name = fn.__name__
                if name in tools and tools[name] != fn:
                    raise ValueError(f"Conflicting agent tool name: {name}")
                tools[name] = fn
        return list(tools.values())


REGISTRY = ModuleRegistry(
    (
        AgentModule(
            "workspace",
            bundle(
                "get_active_geometry",
                "get_active_mesh_info",
                "get_job_status",
                "list_project_jobs",
                "list_project_files",
            ),
            dependencies=(),
        ),
        AgentModule(
            "geometry",
            bundle(
                "list_geometry_capabilities",
                "create_geometry",
                "create_boolean_geometry",
            ),
        ),
        AgentModule(
            "meshing",
            bundle(
                "generate_mesh",
                "confirm_remesh",
                "cancel_pending_remesh",
                "get_pending_remesh",
            ),
        ),
        AgentModule("cad_inspection", bundle("inspect_uploaded_file")),
        AgentModule("selections", bundle(), dependencies=("cad_inspection",)),
        AgentModule(
            "geometry_meshing",
            bundle("create_geometry_and_mesh", "create_boolean_geometry_and_mesh"),
            dependencies=("geometry", "meshing"),
            include_when=("geometry", "meshing"),
        ),
        AgentModule(
            "cad_import",
            bundle("import_uploaded_geometry"),
            dependencies=("geometry", "cad_inspection"),
            include_when=("geometry", "cad_inspection"),
        ),
        AgentModule(
            "cad_meshing",
            bundle("mesh_uploaded_geometry"),
            dependencies=("cad_inspection", "meshing"),
            include_when=("cad_inspection", "meshing"),
        ),
    )
)
