import { useEffect, useRef, useState } from "react";
import { Maximize2, RotateCcw, RefreshCw, Scan } from "lucide-react";
import { MeshQualityPanel } from "./MeshQualityPanel";
import { ViewerScene, type StandardView } from "./ViewerScene";
import { getGeometryPreview } from "../../../services/previews";
import {
  listMeshVersions,
  getMeshVersionPreview,
  type MeshVersion,
} from "../../../services/meshVersions";
import {
  getProjectContext,
  setSelectedMesh,
} from "../../../services/projectContext";

interface SimulationViewerProps {
  projectId: string;
  previewArtifactId: string | null;
  geometryJobId?: string | null;
  refreshRevision?: number;
  navigation?: {
    mode: "geometry" | "mesh";
    meshJobId?: string;
    requestId: number;
  };
  onSelectedMesh?: (id: string) => void;
}

export function SimulationViewer({
  projectId,
  previewArtifactId,
  geometryJobId,
  refreshRevision = 0,
  navigation,
  onSelectedMesh,
}: SimulationViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const labelsRef = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<ViewerScene | null>(null);
  const edgesRef = useRef(false);
  const [viewMode, setViewMode] = useState<"geometry" | "mesh">("geometry");
  const [meshRevision, setMeshRevision] = useState(0);
  const [meshVersions, setMeshVersions] = useState<MeshVersion[]>([]);
  const [versionsGeometryId, setVersionsGeometryId] = useState("");
  const [selectedMeshJobId, setSelectedMeshJobId] = useState("");
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showEdges, setShowEdges] = useState(false);
  const [parallel, setParallel] = useState(false);
  const [geometry, setGeometry] = useState<{
    artifactId: string;
    pointCount: number;
    triangleCount: number;
    quadCount: number;
    lineCount: number;
    dimension: number;
  } | null>(null);

  useEffect(() => {
    if (!containerRef.current || !labelsRef.current) return;
    const scene = new ViewerScene(containerRef.current, labelsRef.current);
    sceneRef.current = scene;
    return () => {
      sceneRef.current = null;
      scene.delete();
    };
  }, []);

  useEffect(() => {
    if (!navigation) return;
    setViewMode(navigation.mode);
    if (navigation.mode === "mesh" && navigation.meshJobId)
      setSelectedMeshJobId(navigation.meshJobId);
  }, [navigation]);

  useEffect(() => {
    const controller = new AbortController();
    if (!geometryJobId) {
      setMeshVersions([]);
      setVersionsGeometryId("");
      setSelectedMeshJobId("");
      setVersionsLoading(false);
      return;
    }
    setVersionsLoading(true);
    setVersionsError(null);
    void Promise.all([
      listMeshVersions(projectId, geometryJobId, controller.signal),
      getProjectContext(projectId, controller.signal),
    ])
      .then(([versions, context]) => {
        if (controller.signal.aborted) return;
        setMeshVersions(versions);
        setVersionsGeometryId(geometryJobId);
        const requested =
          navigation?.mode === "mesh" ? navigation.meshJobId : undefined;
        const remembered =
          context.active_geometry_job_id === geometryJobId
            ? context.selected_mesh_job_id
            : undefined;
        setSelectedMeshJobId(
          (previous) =>
            [requested, previous, remembered, versions[0]?.job_id].find((id) =>
              versions.some((mesh) => mesh.job_id === id),
            ) ?? "",
        );
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setVersionsError(
            err instanceof Error ? err.message : "Unable to list mesh versions",
          );
          setMeshVersions([]);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setVersionsLoading(false);
      });
    return () => controller.abort();
  }, [projectId, geometryJobId, meshRevision, refreshRevision, navigation]);

  const selectedMesh =
    versionsGeometryId === geometryJobId
      ? meshVersions.find((mesh) => mesh.job_id === selectedMeshJobId)
      : undefined;
  const displayKey =
    viewMode === "geometry"
      ? (previewArtifactId ?? "")
      : (selectedMesh?.artifact_id ?? "");
  useEffect(() => {
    const controller = new AbortController();
    const scene = sceneRef.current;
    if (!scene) return;
    setError(null);
    if (!displayKey) {
      scene.hide();
      setGeometry(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    let disposed = false;
    void (
      viewMode === "geometry"
        ? getGeometryPreview(projectId, previewArtifactId!, controller.signal)
        : getMeshVersionPreview(
            projectId,
            geometryJobId!,
            selectedMeshJobId,
            controller.signal,
          )
    )
      .then((preview) => {
        if (disposed) return;
        scene.show(
          preview,
          `${projectId}:${viewMode}:${displayKey}`,
          viewMode === "mesh" && edgesRef.current,
        );
        setParallel(scene.isParallel());
        setGeometry({
          artifactId: displayKey,
          pointCount: preview.point_count,
          triangleCount: preview.triangle_count,
          quadCount: preview.quads?.length ?? 0,
          lineCount: preview.lines?.length ?? 0,
          dimension: preview.dimension ?? 3,
        });
      })
      .catch((err: unknown) => {
        if (!disposed) {
          scene.hide();
          setGeometry(null);
          setError(
            err instanceof Error ? err.message : "Unable to load preview",
          );
        }
      })
      .finally(() => {
        if (!disposed) setLoading(false);
      });
    return () => {
      disposed = true;
      controller.abort();
    };
    // Camera, edges, quality panels and revision counters never rebuild geometry.
  }, [
    projectId,
    previewArtifactId,
    geometryJobId,
    viewMode,
    displayKey,
    selectedMeshJobId,
  ]);

  useEffect(() => {
    if (viewMode !== "mesh" || !geometryJobId || !selectedMesh) return;
    const controller = new AbortController();
    setSelectionError(null);
    void setSelectedMesh(
      projectId,
      geometryJobId,
      selectedMesh.job_id,
      controller.signal,
    )
      .then(() => {
        if (!controller.signal.aborted) onSelectedMesh?.(selectedMesh.job_id);
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted)
          setSelectionError(
            err instanceof Error
              ? err.message
              : "Unable to save mesh selection",
          );
      });
    return () => controller.abort();
  }, [projectId, geometryJobId, viewMode, selectedMesh, onSelectedMesh]);

  const volumeCounts = selectedMesh?.metadata.volume_element_types ?? {};
  const tetraCount = Object.entries(volumeCounts).reduce(
    (total, [name, count]) =>
      total + (name.toLowerCase().startsWith("tetra") ? count : 0),
    0,
  );
  const fallbackTetraCount = Object.entries(
    selectedMesh?.metadata.element_types ?? {},
  ).reduce(
    (total, [name, count]) =>
      total + (name.toLowerCase().startsWith("tetra") ? count : 0),
    0,
  );
  const currentGeometry = geometry?.artifactId === displayKey ? geometry : null;
  const ready = Boolean(currentGeometry) && !loading;
  const standard = (view: StandardView) => {
    sceneRef.current?.standard(view);
    setParallel(sceneRef.current?.isParallel() ?? false);
  };
  const resetCamera = () => {
    sceneRef.current?.reset();
    setParallel(sceneRef.current?.isParallel() ?? false);
  };
  const fullscreen = () => {
    void viewerRef.current?.requestFullscreen();
  };

  return (
    <div className="simulation-viewer" ref={viewerRef}>
      <div className="viewer-toolbar">
        <div
          className="viewer-mode-controls"
          role="group"
          aria-label="Viewer mode"
        >
          <button
            type="button"
            aria-pressed={viewMode === "geometry"}
            onClick={() => setViewMode("geometry")}
          >
            Geometry
          </button>
          <button
            type="button"
            aria-pressed={viewMode === "mesh"}
            disabled={!geometryJobId}
            onClick={() => setViewMode("mesh")}
          >
            Mesh
          </button>
          {viewMode === "mesh" && (
            <>
              <select
                aria-label="Mesh version"
                value={selectedMeshJobId}
                disabled={versionsLoading || !meshVersions.length}
                onChange={(event) => setSelectedMeshJobId(event.target.value)}
              >
                {!meshVersions.length && (
                  <option value="">No mesh versions</option>
                )}
                {meshVersions.map((mesh, index) => (
                  <option key={mesh.job_id} value={mesh.job_id}>
                    {index === 0
                      ? "Latest"
                      : `Version ${meshVersions.length - index}`}{" "}
                    / {mesh.job_id.slice(0, 8)}
                  </option>
                ))}
              </select>
              <button
                type="button"
                aria-label="Refresh mesh"
                title="Refresh mesh"
                onClick={() => setMeshRevision((value) => value + 1)}
              >
                <RefreshCw size={15} />
              </button>
              <label>
                <input
                  type="checkbox"
                  checked={showEdges}
                  onChange={(event) => {
                    const next = event.target.checked;
                    edgesRef.current = next;
                    setShowEdges(next);
                    sceneRef.current?.edges(next);
                  }}
                />
                Edges
              </label>
            </>
          )}
        </div>
        <div className="viewer-tools">
          <button
            type="button"
            disabled={!ready}
            onClick={() => sceneRef.current?.fit()}
            title="Fit to view"
            aria-label="Fit to view"
          >
            <Scan size={17} />
          </button>
          <button
            type="button"
            disabled={!ready}
            onClick={resetCamera}
            title="Reset camera"
            aria-label="Reset camera"
          >
            <RotateCcw size={17} />
          </button>
          <button
            type="button"
            onClick={fullscreen}
            title="Fullscreen"
            aria-label="Fullscreen"
          >
            <Maximize2 size={17} />
          </button>
        </div>
      </div>
      <div
        className="viewer-camera-controls"
        role="group"
        aria-label="Camera controls"
      >
        {(["+X", "-X", "+Y", "-Y", "+Z", "-Z"] as StandardView[]).map(
          (view) => (
            <button
              type="button"
              disabled={!ready}
              key={view}
              aria-label={`View ${view}`}
              onClick={() => standard(view)}
            >
              {view}
            </button>
          ),
        )}
        <button
          type="button"
          disabled={!ready}
          aria-pressed={parallel}
          aria-label="Orthographic projection"
          title="Toggle orthographic / perspective projection"
          onClick={() => {
            sceneRef.current?.projection(!parallel);
            setParallel(!parallel);
          }}
        >
          {parallel ? "Orthographic" : "Perspective"}
        </button>
      </div>
      <div className="vtk-container">
        <div ref={containerRef} className="vtk-render-surface" />
        <div
          ref={labelsRef}
          className="viewer-axis-labels"
          aria-label="XYZ orientation axes"
        >
          <span>X</span>
          <span>Y</span>
          <span>Z</span>
        </div>
        {!displayKey && !loading && !versionsLoading && (
          <div className="viewer-empty-state">
            <h3>
              {viewMode === "geometry"
                ? "No geometry loaded"
                : "No completed mesh"}
            </h3>
            <p>Select an existing geometry or create a new one.</p>
          </div>
        )}
        {(loading ||
          (viewMode === "mesh" && versionsLoading && !displayKey)) && (
          <div className="viewer-empty-state">
            <h3>Loading preview...</h3>
          </div>
        )}
        {error && (
          <div className="viewer-empty-state">
            <h3>Unable to display preview</h3>
            <p role="alert">{error}</p>
          </div>
        )}
      </div>
      {selectionError && (
        <div role="alert" className="viewer-selection-error">
          {selectionError}
        </div>
      )}
      {viewMode === "mesh" && (
        <div
          aria-label="Mesh statistics"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            padding: "7px 12px",
            fontSize: 12,
            color: "#cbd5e1",
            background: "#111827",
            borderTop: "1px solid #334155",
          }}
        >
          {versionsLoading && <span>Loading mesh versions...</span>}
          {versionsError && (
            <span role="alert" style={{ color: "#fb7185" }}>
              {versionsError}
            </span>
          )}
          {!versionsLoading && !versionsError && meshVersions.length === 0 && (
            <span>No completed mesh for this geometry</span>
          )}
          {selectedMesh && (
            <>
              <span>
                <strong>Version:</strong> {selectedMesh.job_id.slice(0, 8)}
              </span>
              <span>
                <strong>Total nodes:</strong>{" "}
                {selectedMesh.metadata.node_count?.toLocaleString() ?? "—"}
              </span>
              <span>
                <strong>All elements:</strong>{" "}
                {selectedMesh.metadata.element_count?.toLocaleString() ?? "—"}
              </span>
              <span>
                <strong>Element family:</strong>{" "}
                {selectedMesh.settings.element_family ?? "tetrahedral"}
              </span>
              <span>
                <strong>Dimension:</strong>{" "}
                {selectedMesh.settings.dimension ?? 3}D
              </span>
              {(selectedMesh.settings.dimension ?? 3) === 3 && (
                <span>
                  <strong>Tetrahedra:</strong>{" "}
                  {(tetraCount || fallbackTetraCount).toLocaleString()}
                </span>
              )}
              {(selectedMesh.settings.dimension ?? 3) === 2 && (
                <span>
                  <strong>Surface cells:</strong>{" "}
                  {Object.entries(selectedMesh.metadata.element_types ?? {})
                    .filter(([name]) => /triangle|quadrangle/i.test(name))
                    .reduce((n, [, v]) => n + v, 0)
                    .toLocaleString()}
                </span>
              )}
              {(selectedMesh.settings.dimension ?? 3) === 1 && (
                <span>
                  <strong>Line cells:</strong>{" "}
                  {Object.entries(selectedMesh.metadata.element_types ?? {})
                    .filter(([name]) => /line/i.test(name))
                    .reduce((n, [, v]) => n + v, 0)
                    .toLocaleString()}
                </span>
              )}
              <span>
                <strong>Size:</strong> {selectedMesh.settings.min_size ?? "?"}–
                {selectedMesh.settings.max_size ?? "?"}
              </span>
              <span>
                <strong>Versions:</strong> {meshVersions.length}
              </span>
            </>
          )}
        </div>
      )}
      {viewMode === "mesh" && geometryJobId && selectedMeshJobId && (
        <MeshQualityPanel
          projectId={projectId}
          geometryJobId={geometryJobId}
          meshJobId={selectedMeshJobId}
          revision={meshRevision}
        />
      )}
      <div className="viewer-footer">
        <span>
          {currentGeometry
            ? `${viewMode === "mesh" ? "Surface points" : "Points"}: ${currentGeometry.pointCount}`
            : "Geometry: None"}
        </span>
        <span>
          {currentGeometry
            ? `${currentGeometry.dimension}D · ${currentGeometry.lineCount} lines · ${currentGeometry.triangleCount} triangles · ${currentGeometry.quadCount} quads`
            : "Units: Not specified"}
        </span>
      </div>
    </div>
  );
}
