import { useEffect, useRef, useState } from "react";
import { Maximize2, RotateCcw, RefreshCw, Scan } from "lucide-react";
import { MeshQualityPanel } from "./MeshQualityPanel";
import { SelectionPicker } from "../../../components/SelectionPicker";
import { ViewerScene, type StandardView } from "./ViewerScene";
import { getGeometryPreview } from "../../../services/previews";
import { geometrySelection, type CadEntity, type EntityDimension } from "../../../services/cadEntities";
import type { GeometryPreview } from "../../../services/previews";
import { selectionLimitation } from "./cadPicking";
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
  const selectionQueue = useRef<Promise<unknown>>(Promise.resolve());
  const [selectedEntity, setSelectedEntity] = useState<CadEntity | null>(null);
  const [selectionDimension, setSelectionDimension] = useState<EntityDimension>(2);
  const selectionDimensionRef = useRef<EntityDimension>(2);
  const [cadPreview, setCadPreview] = useState<GeometryPreview | null>(null);
  const [entitySaving, setEntitySaving] = useState(false);
  const [cadRevision, setCadRevision] = useState<string | null>(null);
  const [entityError, setEntityError] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<"geometry" | "mesh">("geometry");
  const [showGeometryInspector, setShowGeometryInspector] = useState(true);
  const [showMeshInspector, setShowMeshInspector] = useState(true);
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
    setSelectedEntity(null);
    setCadRevision(null);
    setCadPreview(null);
    setEntityError(null);
  }, [projectId, previewArtifactId]);

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
  const displayedGeometryJobId = viewMode === "mesh" ? geometryJobId : undefined;
  const displayedMeshJobId = viewMode === "mesh" ? selectedMesh?.job_id : undefined;
  useEffect(() => {
    const controller = new AbortController();
    const scene = sceneRef.current;
    if (!scene) return;
    scene.onEntityPicked = undefined;
    scene.onSelectionUnavailable = undefined;
    scene.hide();
    setEntitySaving(false);
    setError(null);
    if (!displayKey) {
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
            displayedGeometryJobId!,
            displayedMeshJobId!,
            controller.signal,
          )
    )
      .then(async (preview) => {
        if (disposed) return;
        scene.setSelectionMode(selectionDimensionRef.current);
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
        if (viewMode === "geometry" && preview.geometry_revision_id) {
          const revision = preview.geometry_revision_id;
          setCadRevision(revision);
          setCadPreview(preview);
          setEntityError(null);
          try {
            // Wait for previous writes before restoring selection on mode changes.
            await selectionQueue.current;
            if (disposed) return;
            const saved = await geometrySelection(projectId, controller.signal);
            if (disposed) return;
            const entity = saved.selection?.geometry_revision_id === revision ? saved.selection : null;
            setSelectedEntity(entity);
            scene.selectEntity(revision, entity?.entity_key ?? null);
          } catch (err) {
            if (disposed) return;
            setSelectedEntity(null);
            scene.selectEntity(revision, null);
            setEntityError(err instanceof Error ? err.message : "Unable to restore CAD selection");
          }
          let sequence = 0;
          scene.onSelectionUnavailable = message => { if (!disposed) setEntityError(message); };
          scene.onEntityPicked = (pickedRevision, entity) => {
            if (disposed || pickedRevision !== revision) return;
            const current = ++sequence;
            setEntitySaving(true);
            setEntityError(null);
            // Serialize writes: quick successive clicks must not commit out of order.
            selectionQueue.current = selectionQueue.current.catch(() => undefined).then(async () => {
              if (disposed) return;
              try {
                const saved = await geometrySelection(projectId, undefined, {
                  geometry_revision_id: revision, dimension: entity?.dimension ?? null, tag: entity?.tag ?? null,
                });
                if (disposed || current !== sequence) return;
                setSelectedEntity(saved.selection);
                scene.selectEntity(revision, saved.selection?.entity_key ?? null);
              } catch (err) {
                if (disposed || current !== sequence) return;
                setSelectedEntity(null);
                scene.selectEntity(revision, null);
                setEntityError(err instanceof Error ? err.message : "Unable to save CAD selection");
              } finally {
                if (!disposed && current === sequence) setEntitySaving(false);
              }
            });
          };
        }
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
      scene.onEntityPicked = undefined;
      scene.onSelectionUnavailable = undefined;
      controller.abort();
    };
    // Camera, edges, quality panels and revision counters never rebuild geometry.
  }, [
    projectId,
    previewArtifactId,
    displayedGeometryJobId,
    viewMode,
    displayKey,
    displayedMeshJobId,
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
  const inspectorVisible = viewMode === "geometry" ? showGeometryInspector : showMeshInspector;
  const inspectorName = viewMode === "geometry" ? "Geometry Inspector" : "Mesh Inspector";
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
          {viewMode === "geometry" && (
            <SelectionPicker
              label="CAD selection mode"
              heading="Selection mode"
              placeholder="Face (2D)"
              value={String(selectionDimension)}
              options={["Vertex (0D)", "Edge (1D)", "Face (2D)", "Body (3D)"].map((label, dimension) => ({ value: String(dimension), label }))}
              disabled={!cadRevision}
              onSelect={value => {
                const dimension = Number(value) as EntityDimension;
                selectionDimensionRef.current = dimension;
                setSelectionDimension(dimension);
                setEntityError(null);
                sceneRef.current?.setSelectionMode(dimension);
              }}
            />
          )}
          {viewMode === "mesh" && (
            <>
              <SelectionPicker
                label="Mesh version"
                heading="Mesh versions"
                placeholder={versionsLoading ? "Loading mesh versions..." : "No mesh versions"}
                value={selectedMeshJobId}
                disabled={versionsLoading || !meshVersions.length}
                onSelect={setSelectedMeshJobId}
                options={meshVersions.map((mesh, index) => ({
                  value: mesh.job_id,
                  label: `${index === 0 ? "Latest" : `Version ${meshVersions.length - index}`} / ${mesh.job_id.slice(0, 8)}`,
                }))}
              />
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
            aria-expanded={inspectorVisible}
            aria-controls={viewMode === "geometry" ? "geometry-inspector" : "mesh-inspector"}
            disabled={viewMode === "geometry" ? !cadRevision : !geometryJobId}
            onClick={() => {
              if (viewMode === "geometry") setShowGeometryInspector(visible => !visible);
              else setShowMeshInspector(visible => !visible);
            }}
          >
            {inspectorVisible ? "Hide" : "Show"} {inspectorName}
          </button>
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
        <div ref={containerRef} className="vtk-render-surface" tabIndex={0}
          aria-label="3D viewer. Choose a CAD entity selection mode and click to select. Escape clears selection." />
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
      {viewMode === "geometry" && !showGeometryInspector && entityError && (
        <div role="alert" className="viewer-selection-error">{entityError}</div>
      )}
      {viewMode === "geometry" && cadRevision && (
        <section id="geometry-inspector" className="geometry-inspector" aria-label="Geometry Inspector" aria-busy={entitySaving} hidden={!showGeometryInspector}>
          <div className="geometry-inspector-heading">
            <strong>Geometry Inspector · {selectedEntity?.label ?? "No selection"}</strong>
            <button type="button" disabled={!selectedEntity || entitySaving}
              onClick={() => sceneRef.current?.onEntityPicked?.(cadRevision, null)}>Clear selection</button>
          </div>
          {cadPreview?.geometry_revision_id === cadRevision && selectionLimitation(cadPreview, selectionDimension) && <p role="status">{selectionLimitation(cadPreview, selectionDimension)}</p>}
          {entityError && <p role="alert">{entityError}</p>}
          {entitySaving && <p role="status">Saving geometry selection...</p>}
          {selectedEntity ? <dl>
            <dt>Entity</dt><dd>{selectedEntity.label} ({selectedEntity.dimension}D)</dd>
            <dt>Geometry type</dt><dd>{selectedEntity.geometric_type}</dd>
            {selectedEntity.coordinates && <><dt>Coordinates (XYZ)</dt><dd>{selectedEntity.coordinates.map(v => Number(v.toPrecision(8))).join(", ")} {selectedEntity.coordinate_units}</dd></>}
            {selectedEntity.length !== null && <><dt>Length</dt><dd>{selectedEntity.length.toLocaleString(undefined, { maximumSignificantDigits: 8 })} {selectedEntity.measure_units}</dd></>}
            {selectedEntity.area !== null && <><dt>Area</dt><dd>{selectedEntity.area.toLocaleString(undefined, { maximumSignificantDigits: 8 })} {selectedEntity.measure_units}</dd></>}
            {selectedEntity.volume !== null && <><dt>Volume</dt><dd>{selectedEntity.volume.toLocaleString(undefined, { maximumSignificantDigits: 8 })} {selectedEntity.measure_units}</dd></>}
            <dt>Bounds (min XYZ → max XYZ)</dt><dd>{selectedEntity.bounds.map(v => Number(v.toPrecision(6))).join(", ")} {selectedEntity.coordinate_units}</dd>
            {selectedEntity.normal_information && <><dt>Normal</dt><dd>{selectedEntity.normal?.map(v => Number(v.toPrecision(6))).join(", ") ?? "Varies over surface"}. {selectedEntity.normal_information}</dd></>}
          </dl> : <p>Choose Vertex, Edge, Face or Body mode and click a CAD entity to inspect it.</p>}
        </section>
      )}
      {selectionError && (
        <div role="alert" className="viewer-selection-error">
          {selectionError}
        </div>
      )}
      {viewMode === "mesh" && (
        <section id="mesh-inspector" className="mesh-inspector" aria-label="Mesh Inspector" hidden={!showMeshInspector}>
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
          {geometryJobId && selectedMeshJobId && (
            <MeshQualityPanel
              projectId={projectId}
              geometryJobId={geometryJobId}
              meshJobId={selectedMeshJobId}
              revision={meshRevision}
            />
          )}
        </section>
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
