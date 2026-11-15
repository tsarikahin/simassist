"""Isolated STEP parser, run in a short-lived subprocess, never the API process."""

import json
import sys
from pathlib import Path

import gmsh


def inspect_step(path: Path):
    gmsh.initialize()
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setString("Geometry.OCCTargetUnit", "MM")
        gmsh.model.add("uploaded_step")
        gmsh.model.occ.importShapes(str(path), format="step")
        gmsh.model.occ.synchronize()
        from simassist.simulation.geometry.gmsh_adapter import GmshGeometryAdapter

        metadata = GmshGeometryAdapter._get_metadata().model_dump(mode="json")
        if metadata["dimension"] not in (2, 3):
            raise ValueError("STEP import requires surfaces or solid volumes")
        return {
            **metadata,
            "coordinate_units": "mm",
            "diagnostic": "CAD topology inspected; not a guarantee of meshing suitability or feature preservation",
        }
    finally:
        gmsh.finalize()


if __name__ == "__main__":
    try:
        print(json.dumps(inspect_step(Path(sys.argv[1]))))
    except Exception:  # noqa: BLE001 - isolate untrusted native parser failures
        print(json.dumps({"error": "STEP could not be parsed as a nonempty CAD model"}))
        sys.exit(1)
