
import {
  Box,
  Grid3X3,
  Play,
  BarChart3,
  ChevronDown,
  FolderOpen,
} from "lucide-react";

export function ProjectExplorer() {
  return (
    <div className="project-explorer">
      <div className="project-name">
        <FolderOpen size={17} />
        Cantilever Beam
        <ChevronDown size={15} />
      </div>

      <div className="project-tree">
        <div className="tree-item">
          <Box size={16} />
          Geometry
        </div>

        <div className="tree-item">
          <Grid3X3 size={16} />
          Mesh
        </div>

        <div className="tree-item">
          <Play size={16} />
          Simulation
        </div>

        <div className="tree-item">
          <BarChart3 size={16} />
          Results
        </div>
      </div>

      <div className="solver-settings">
        <h4>Solver Configuration</h4>

        <label htmlFor="solver">Solver</label>
        <select id="solver" defaultValue="calculix">
          <option value="calculix">CalculiX</option>
          <option value="aster">Code_Aster</option>
          <option value="elmer">Elmer FEM</option>
        </select>

        <label htmlFor="analysis">Analysis Type</label>
        <select id="analysis" defaultValue="static">
          <option value="static">Static Structural</option>
          <option value="nonlinear">Nonlinear Structural</option>
          <option value="thermal">Thermal</option>
        </select>
      </div>
    </div>
  );
}
