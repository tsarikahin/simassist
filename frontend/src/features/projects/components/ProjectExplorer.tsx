
import { useEffect, useState } from "react";

import {
  Box,
  Grid3X3,
  Play,
  BarChart3,
  ChevronDown,
  FolderOpen,
  RefreshCw,
} from "lucide-react";

import {
  getProjectGeometries,
  type ProjectGeometry,
} from "../../../services/projectContext";

interface ProjectExplorerProps {
  projectId: string;
  activeGeometryJobId: string | null;
  revision: number;
  onSelectGeometry: (geometry: ProjectGeometry) => void;
  selectionError?: string | null;
}

function geometryName(job: ProjectGeometry): string {
  if (
    typeof job.input.name === "string" &&
    job.input.name.trim()
  ) {
    return job.input.name;
  }

  const primitive = job.input.definition?.primitive;

  if (typeof primitive === "string") {
    return `${primitive} (${job.id.slice(0, 8)})`;
  }

  return `Geometry ${job.id.slice(0, 8)}`;
}

export function ProjectExplorer({
  projectId,
  activeGeometryJobId,
  revision,
  onSelectGeometry,
  selectionError,
}: ProjectExplorerProps) {
  const [geometries, setGeometries] = useState<
    ProjectGeometry[]
  >([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();

    async function loadGeometries() {
      setLoading(true);
      setError(null);

      try {
        const items = await getProjectGeometries(
          projectId,
          controller.signal,
        );

        if (!controller.signal.aborted) {
          setGeometries(items);
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(
            err instanceof Error
              ? err.message
              : "Unable to load geometries",
          );
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      }
    }

    void loadGeometries();

    return () => controller.abort();
  }, [projectId, revision, refresh]);

  return (
    <div className="project-explorer">
      <div className="project-name">
        <FolderOpen size={17} />
        Untitled Project
        <ChevronDown size={15} />
      </div>

      <div className="project-tree">
        <div
          className="tree-item"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 8,
            }}
          >
            <Box size={16} />
            Geometry
          </span>

          <button
            type="button"
            title="Refresh geometries"
            aria-label="Refresh geometries"
            onClick={() =>
              setRefresh((previous) => previous + 1)
            }
            style={{
              border: "none",
              background: "transparent",
              color: "inherit",
              cursor: "pointer",
            }}
          >
            <RefreshCw size={14} />
          </button>
        </div>

        {loading && (
          <p style={{ paddingLeft: 24, fontSize: 12 }}>
            Loading geometries...
          </p>
        )}

        {!loading && geometries.length === 0 && (
          <p
            style={{
              paddingLeft: 24,
              fontSize: 12,
              opacity: 0.65,
            }}
          >
            No completed geometries
          </p>
        )}

        {geometries.map((geometry) => {
          const selected =
            geometry.id === activeGeometryJobId;

          return (
            <button
              key={geometry.id}
              type="button"
              onClick={() => onSelectGeometry(geometry)}
              title={geometry.id}
              aria-pressed={selected}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                width: "100%",
                padding: "8px 10px 8px 27px",
                border: "none",
                borderLeft: selected
                  ? "3px solid #60a5fa"
                  : "3px solid transparent",
                borderRadius: 4,
                background: selected
                  ? "rgba(96,165,250,0.12)"
                  : "transparent",
                color: "inherit",
                cursor: "pointer",
                textAlign: "left",
                fontSize: 12,
              }}
            >
              <Box size={14} />

              <span
                style={{
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {geometryName(geometry)}
              </span>
            </button>
          );
        })}

        {(error || selectionError) && (
          <p
            role="alert"
            style={{
              paddingLeft: 24,
              fontSize: 12,
              color: "#fb7185",
            }}
          >
            {error || selectionError}
          </p>
        )}

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
