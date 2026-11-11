from pathlib import Path

import meshio


def convert_mesh_to_vtu(
    input_path: Path,
    output_path: Path,
) -> Path:
    """Convert Gmsh mesh to VTK UnstructuredGrid."""

    mesh = meshio.read(input_path)

    volume_cells = [cell for cell in mesh.cells if cell.type in {"tetra", "hexahedron"}]

    if not volume_cells:
        raise ValueError("No supported 3D volume elements found.")

    converted = meshio.Mesh(
        points=mesh.points,
        cells=volume_cells,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    meshio.write(output_path, converted, file_format="vtu")

    return output_path
