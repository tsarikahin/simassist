
import { useEffect, useState } from "react";

import {
  Box,
  Play,
  BarChart3,
  ChevronDown,
  ChevronRight,
  GitBranch,
  FolderOpen,
  RefreshCw,
  Pencil, Trash2,
} from "lucide-react";

import { listMeshVersions, type MeshVersion } from "../../../services/meshVersions";

import {
  getProjectGeometries,
  renameGeometry, deleteGeometry,
  type ProjectGeometry,
} from "../../../services/projectContext";

interface ProjectExplorerProps {
  projectId: string;
  activeGeometryJobId: string | null;
  revision: number;
  onSelectGeometry: (geometry: ProjectGeometry) => void;
  onSelectMesh: (geometry: ProjectGeometry, meshJobId: string) => void;
  meshRevision?: number;
  selectionError?: string | null;
  onGeometryChanged: (deletedJobId?: string) => void;
}

function geometryName(job: ProjectGeometry): string {
  if (
    typeof job.input.name === "string" &&
    job.input.name.trim()
  ) {
    return job.input.name + (job.input.definition?.source === "cad_import" && !job.input.name.endsWith("[Imported]") ? " [Imported]" : "");
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
  onSelectMesh,
  meshRevision = 0,
  selectionError,
  onGeometryChanged,
}: ProjectExplorerProps) {
  const [geometries, setGeometries] = useState<
    ProjectGeometry[]
  >([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const [expandedGeometryId, setExpandedGeometryId] = useState<string | null>(null);
  const [meshLists, setMeshLists] = useState<Record<string, MeshVersion[]>>({});
  const [meshLoading, setMeshLoading] = useState(false);
  const [meshError, setMeshError] = useState<string | null>(null);
  const [selectedMeshId, setSelectedMeshId] = useState<string | null>(null);

  // Query only the expanded geometry. Old mesh jobs remain intact.
  useEffect(() => {
    if (!expandedGeometryId) return;
    const controller = new AbortController();
    setMeshLoading(true);
    setMeshError(null);
    void listMeshVersions(projectId, expandedGeometryId, controller.signal)
      .then(items => {
        if (!controller.signal.aborted) {
          setMeshLists(previous => ({...previous, [expandedGeometryId]: items}));
        }
      })
      .catch(err => {
        if (!controller.signal.aborted) setMeshError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => { if (!controller.signal.aborted) setMeshLoading(false); });
    return () => controller.abort();
  }, [projectId, expandedGeometryId, meshRevision, refresh, revision]);

  useEffect(() => {
    setExpandedGeometryId(null);
    setMeshLists({});
    setSelectedMeshId(null);
  }, [projectId]);

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
        Geometry / Mesh
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
            Geometry / Mesh
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
          const selected = geometry.id === activeGeometryJobId;
          const expanded = geometry.id === expandedGeometryId;
          const versions = meshLists[geometry.id] ?? [];
          return (
            <div key={geometry.id} className="geometry-tree-node">
              <div className="geometry-tree-row" style={{display:"flex",alignItems:"center",width:"100%"}}>
                <button type="button" className="geometry-expand"
                  aria-label={`${expanded ? "Collapse" : "Expand"} mesh versions for ${geometryName(geometry)}`}
                  aria-expanded={expanded}
                  title={expanded ? "Hide mesh versions" : "Show mesh versions"}
                  onClick={() => setExpandedGeometryId(expanded ? null : geometry.id)}>
                  {expanded ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
                </button>
                <button type="button" onClick={() => {
                  setSelectedMeshId(null);
                  onSelectGeometry(geometry);
                }} title={`Show geometry: ${geometryName(geometry)}`}
                  aria-pressed={selected && selectedMeshId === null}
                  className="geometry-tree-label"
                  style={{display:"flex",alignItems:"center",gap:8,flex:1,minWidth:0,
                    padding:"8px 4px",border:"none",
                    borderLeft:selected && selectedMeshId === null ? "3px solid #60a5fa" : "3px solid transparent",
                    borderRadius:4,background:selected && selectedMeshId === null ? "rgba(96,165,250,0.12)" : "transparent",
                    color:"inherit",cursor:"pointer",textAlign:"left",fontSize:12}}>
                  <Box size={14} style={{flexShrink:0}}/>
                  <span style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>{geometryName(geometry)}</span>
                </button>
                <button type="button" title="Rename geometry" aria-label={`Rename ${geometryName(geometry)}`}
                  className="geometry-action" onClick={() => {
                    const name = window.prompt("New geometry name", geometryName(geometry));
                    if (!name?.trim()) return;
                    void renameGeometry(projectId, geometry.id, name.trim())
                      .then(() => {setRefresh(r => r+1);onGeometryChanged();})
                      .catch(err => setError(String(err)));
                  }}><Pencil size={13}/></button>
                <button type="button" title="Delete geometry (preserve archived artifacts)"
                  aria-label={`Delete ${geometryName(geometry)}`}
                  className="geometry-action" onClick={() => {
                    if (!window.confirm(`Hide '${geometryName(geometry)}' from this project? Existing mesh/jobs and artifacts remain archived.`)) return;
                    void deleteGeometry(projectId, geometry.id)
                      .then(() => {
                        if (expandedGeometryId === geometry.id) setExpandedGeometryId(null);
                        setSelectedMeshId(null);
                        setRefresh(r=>r+1);
                        onGeometryChanged(geometry.id);
                      }).catch(err => setError(String(err)));
                  }}><Trash2 size={13}/></button>
              </div>
              {expanded && (
                <div className="geometry-mesh-children" role="group" aria-label={`Mesh versions of ${geometryName(geometry)}`}>
                  {meshLoading && <div className="geometry-mesh-hint">Loading meshes...</div>}
                  {!meshLoading && meshError && <div role="alert" className="geometry-mesh-hint" style={{color:"#fb7185"}}>{meshError}</div>}
                  {!meshLoading && !meshError && versions.length===0 && <div className="geometry-mesh-hint">No mesh versions</div>}
                  {!meshLoading && !meshError && versions.map((mesh, index) => (
                    <button type="button" key={mesh.job_id} className="geometry-mesh-version"
                      aria-pressed={selected && selectedMeshId === mesh.job_id}
                      title={`Mesh job ${mesh.job_id}`}
                      onClick={() => {
                        setSelectedMeshId(mesh.job_id);
                        onSelectMesh(geometry, mesh.job_id);
                      }}>
                      <GitBranch size={13} style={{flexShrink:0}} />
                      <span style={{overflow:"hidden",textOverflow:"ellipsis",whiteSpace:"nowrap"}}>
                        {mesh.settings.element_family ?? "Mesh"} · v{versions.length-index}
                      </span>
                      <span className="geometry-mesh-short-id">{mesh.job_id.slice(0,8)}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
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
