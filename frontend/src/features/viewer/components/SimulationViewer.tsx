import { MeshQualityPanel } from "./MeshQualityPanel";

import { useEffect, useRef, useState } from "react";
import { Maximize2, RotateCcw, RefreshCw } from "lucide-react";
import { getLatestMeshPreview } from "../../../services/meshPreviews";
import { listMeshVersions, getMeshVersionPreview, type MeshVersion } from "../../../services/meshVersions";

import "@kitware/vtk.js/Rendering/Profiles/All";

import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";

import {
  getGeometryPreview,
  type GeometryPreview,
} from "../../../services/previews";

type VtkInstance = ReturnType<
  typeof vtkGenericRenderWindow.newInstance
>;

interface SimulationViewerProps {
  projectId: string;
  previewArtifactId: string | null;
  geometryJobId?: string | null;
  refreshRevision?: number;
}

function createPolyData(preview: GeometryPreview) {
  const polyData = vtkPolyData.newInstance();

  const coordinates = new Float32Array(
    preview.points.length * 3,
  );

  preview.points.forEach((point, index) => {
    coordinates[index * 3] = point[0];
    coordinates[index * 3 + 1] = point[1];
    coordinates[index * 3 + 2] = point[2];
  });

  polyData.getPoints().setData(coordinates, 3);

  // VTK cell format:
  // [3, pointA, pointB, pointC, 3, ...]
  const cells = new Uint32Array(
    preview.triangles.length * 4,
  );

  preview.triangles.forEach((triangle, index) => {
    const offset = index * 4;

    cells[offset] = 3;
    cells[offset + 1] = triangle[0];
    cells[offset + 2] = triangle[1];
    cells[offset + 3] = triangle[2];
  });

  const quadCells = new Uint32Array((preview.quads?.length ?? 0) * 5);
  (preview.quads ?? []).forEach((quad, index) => {
    const offset = index * 5;
    quadCells[offset] = 4;
    quadCells.set(quad, offset + 1);
  });
  const polygons = new Uint32Array(cells.length + quadCells.length);
  polygons.set(cells);
  polygons.set(quadCells, cells.length);
  polyData.getPolys().setData(polygons);

  const lineCells = new Uint32Array((preview.lines?.length ?? 0) * 3);
  (preview.lines ?? []).forEach((line, index) => {
    const offset = index * 3;
    lineCells[offset] = 2;
    lineCells.set(line, offset + 1);
  });
  polyData.getLines().setData(lineCells);
  return polyData;
}

export function SimulationViewer({
  projectId,
  previewArtifactId,
  geometryJobId,
  refreshRevision = 0,
}: SimulationViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const vtkRef = useRef<VtkInstance | null>(null);

  const [viewMode, setViewMode] = useState<"geometry" | "mesh">("geometry");
  const [meshRevision, setMeshRevision] = useState(0);
  const [meshVersions, setMeshVersions] = useState<MeshVersion[]>([]);
  const [selectedMeshJobId, setSelectedMeshJobId] = useState<string>("");
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geometry, setGeometry] = useState<{
    artifactId: string;
    pointCount: number;
    triangleCount: number;
    quadCount: number;
    lineCount: number;
    dimension: number;
  } | null>(null);

  // Discover all completed meshes for the selected geometry.
  // Keep the current selection on refresh when it still exists.
  useEffect(() => {
    const controller = new AbortController();
    if (!geometryJobId) {
      setMeshVersions([]);
      setSelectedMeshJobId("");
      setVersionsError(null);
      return () => controller.abort();
    }
    setVersionsLoading(true);
    setVersionsError(null);
    void listMeshVersions(projectId, geometryJobId, controller.signal)
      .then((versions) => {
        if (controller.signal.aborted) return;
        setMeshVersions(versions);
        setSelectedMeshJobId((previous) =>
          versions.some((mesh) => mesh.job_id === previous)
            ? previous : (versions[0]?.job_id ?? ""),
        );
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setVersionsError(err instanceof Error ? err.message : "Unable to list mesh versions");
        setMeshVersions([]);
        setSelectedMeshJobId("");
      })
      .finally(() => {
        if (!controller.signal.aborted) setVersionsLoading(false);
      });
    return () => controller.abort();
  }, [projectId, geometryJobId, meshRevision, refreshRevision]);

  const selectedMesh = meshVersions.find((mesh) => mesh.job_id === selectedMeshJobId);
  const volumeCounts = selectedMesh?.metadata.volume_element_types ?? {};
  const tetraCount = Object.entries(volumeCounts).reduce(
    (total, [name, count]) => total + (name.toLowerCase().startsWith("tetra") ? count : 0),
    0,
  );
  const fallbackTetraCount = Object.entries(selectedMesh?.metadata.element_types ?? {}).reduce(
    (total, [name, count]) => total + (name.toLowerCase().startsWith("tetra") ? count : 0),
    0,
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const vtkWindow = vtkGenericRenderWindow.newInstance({
      background: [0.043, 0.071, 0.125],
    });

    vtkWindow.setContainer(container);
    vtkWindow.resize();
    vtkRef.current = vtkWindow;

    const resizeObserver = new ResizeObserver(() => {
      vtkWindow.resize();
      vtkWindow.getRenderWindow().render();
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      vtkRef.current = null;
      vtkWindow.delete();
    };
  }, []);

  useEffect(() => {
    const vtkWindow = vtkRef.current;
    if (!vtkWindow) return;

    const renderer = vtkWindow.getRenderer();
    const renderWindow = vtkWindow.getRenderWindow();

    renderer.removeAllViewProps();
    renderWindow.render();

    if (viewMode === "geometry" ? !previewArtifactId : !geometryJobId) {
      setLoading(false);
      setError(null);
      setGeometry(null);
      return;
    }

    const controller = new AbortController();
    let disposed = false;
    let actor: ReturnType<typeof vtkActor.newInstance> | null =
      null;
    let mapper: ReturnType<typeof vtkMapper.newInstance> | null =
      null;
    let polyData: ReturnType<
      typeof vtkPolyData.newInstance
    > | null = null;

    async function load() {
      setLoading(true);
      setError(null);
      setGeometry(null);

      try {
        const preview = viewMode === "mesh"
          ? selectedMeshJobId
            ? await getMeshVersionPreview(projectId, geometryJobId!, selectedMeshJobId, controller.signal)
            : await getLatestMeshPreview(projectId, geometryJobId!, controller.signal)
          : await getGeometryPreview(projectId, previewArtifactId!, controller.signal);

        if (disposed) return;

        polyData = createPolyData(preview);
        mapper = vtkMapper.newInstance();
        mapper.setInputData(polyData);

        actor = vtkActor.newInstance();
        actor.setMapper(mapper);
        const property = actor.getProperty();

        property.setColor(0.35, 0.65, 0.95);
        property.setAmbient(0.25);
        property.setDiffuse(0.75);
        property.setSpecular(0.3);
        property.setSpecularPower(25);
        property.setInterpolationToPhong();
        if (viewMode === "mesh") {
          property.setEdgeVisibility(true);
          property.setEdgeColor(0.05, 0.13, 0.22);
          property.setLineWidth(3);
        }

        renderer.addActor(actor);

        renderer.resetCamera();

        const camera = renderer.getActiveCamera();
        const bounds = actor.getBounds();

        const center: [number, number, number] = [
          (bounds[0] + bounds[1]) / 2,
          (bounds[2] + bounds[3]) / 2,
          (bounds[4] + bounds[5]) / 2,
        ];

        const size = Math.max(
          bounds[1] - bounds[0],
          bounds[3] - bounds[2],
          bounds[5] - bounds[4],
          1,
        );

        camera.setFocalPoint(...center);
        camera.setPosition(
          center[0] + size * 1.5,
          center[1] - size * 1.8,
          center[2] + size * 1.2,
        );
        camera.setViewUp(0, 0, 1);

        renderer.resetCameraClippingRange();
        renderWindow.render();

        setGeometry({
          artifactId: viewMode === "mesh" ? geometryJobId! : previewArtifactId!,
          pointCount: preview.point_count,
          triangleCount: preview.triangle_count,
          quadCount: preview.quads?.length ?? 0,
          lineCount: preview.lines?.length ?? 0,
          dimension: preview.dimension ?? 3,
        });
      } catch (err) {
        if (disposed) return;

        setError(
          err instanceof Error
            ? err.message
            : "Unable to load geometry",
        );
      } finally {
        if (!disposed) setLoading(false);
      }
    }

    void load();

    return () => {
      disposed = true;
      controller.abort();

      if (actor) {
        renderer.removeActor(actor);
        actor.delete();
      }

      mapper?.delete();
      polyData?.delete();
    };
  }, [projectId, previewArtifactId, geometryJobId, viewMode, meshRevision, refreshRevision, selectedMeshJobId]);

  function resetCamera() {
    vtkRef.current?.getRenderer().resetCamera();
    vtkRef.current?.getRenderWindow().render();
  }

  function fullscreen() {
    void containerRef.current?.requestFullscreen();
  }

  const currentGeometry =
    geometry?.artifactId === (viewMode === "mesh" ? geometryJobId : previewArtifactId)
      ? geometry
      : null;

  return (
    <div className="simulation-viewer">
      <div className="viewer-toolbar">
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span>Simulation Viewport</span>
            <div role="group" aria-label="Viewer mode" style={{ display: "flex", gap: 4 }}>
              <button type="button" aria-pressed={viewMode === "geometry"}
                onClick={() => setViewMode("geometry")}
                style={{ color: viewMode === "geometry" ? "#60a5fa" : "inherit" }}>
                Geometry
              </button>
              <button type="button" aria-pressed={viewMode === "mesh"}
                disabled={!geometryJobId}
                onClick={() => setViewMode("mesh")}
                style={{ color: viewMode === "mesh" ? "#60a5fa" : "inherit" }}>
                Mesh
              </button>
              {viewMode === "mesh" && (
                <select
                  aria-label="Mesh version"
                  value={selectedMeshJobId}
                  disabled={versionsLoading || meshVersions.length === 0}
                  onChange={(event) => setSelectedMeshJobId(event.target.value)}
                  style={{ maxWidth: 230, background: "#1e293b", color: "#e2e8f0", border: "1px solid #475569", borderRadius: 4, padding: 4 }}
                >
                  {meshVersions.length === 0 && <option value="">No mesh versions</option>}
                  {meshVersions.map((mesh, index) => (
                    <option key={mesh.job_id} value={mesh.job_id}>
                      {index === 0 ? "Latest" : `Version ${meshVersions.length - index}`} · {mesh.job_id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              )}
              {viewMode === "mesh" && (
                <button type="button" aria-label="Refresh mesh" title="Refresh mesh"
                  onClick={() => setMeshRevision((value) => value + 1)}>
                  <RefreshCw size={15} />
                </button>
              )}
            </div>
          </div>

        <div className="viewer-tools">
          <button
            type="button"
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

      <div className="vtk-container">
        <div
          ref={containerRef}
          className="vtk-render-surface"
        />

        {!(viewMode === "mesh" ? geometryJobId : previewArtifactId) && (
          <div className="viewer-empty-state">
            <h3>No geometry loaded</h3>
            <p>Select an existing geometry or create a new one.</p>
          </div>
        )}

        {loading && (
          <div className="viewer-empty-state">
            <h3>Loading geometry...</h3>
          </div>
        )}

        {error && (
          <div className="viewer-empty-state">
            <h3>Unable to display geometry</h3>
            <p>{error}</p>
          </div>
        )}
      </div>

      {viewMode === "mesh" && (
        <div aria-label="Mesh statistics" style={{ display: "flex", flexWrap: "wrap", gap: 16, padding: "7px 12px", fontSize: 12, color: "#cbd5e1", background: "#111827", borderTop: "1px solid #334155" }}>
          {versionsLoading && <span>Loading mesh versions...</span>}
          {versionsError && <span role="alert" style={{ color: "#fb7185" }}>{versionsError}</span>}
          {!versionsLoading && !versionsError && meshVersions.length === 0 && <span>No completed mesh for this geometry</span>}
          {selectedMesh && (
            <>
              <span><strong>Version:</strong> {selectedMesh.job_id.slice(0, 8)}</span>
              <span><strong>Total nodes:</strong> {selectedMesh.metadata.node_count?.toLocaleString() ?? "—"}</span>
              <span><strong>All elements:</strong> {selectedMesh.metadata.element_count?.toLocaleString() ?? "—"}</span>
              <span><strong>Element family:</strong> {selectedMesh.settings.element_family ?? "tetrahedral"}</span>
              <span><strong>Dimension:</strong> {selectedMesh.settings.dimension ?? 3}D</span>
              {(selectedMesh.settings.dimension ?? 3) === 3 && <span><strong>Tetrahedra:</strong> {(tetraCount || fallbackTetraCount).toLocaleString()}</span>}
              {(selectedMesh.settings.dimension ?? 3) === 2 && <span><strong>Surface cells:</strong> {Object.entries(selectedMesh.metadata.element_types ?? {}).filter(([name]) => /triangle|quadrangle/i.test(name)).reduce((n, [,v]) => n+v,0).toLocaleString()}</span>}
              {(selectedMesh.settings.dimension ?? 3) === 1 && <span><strong>Line cells:</strong> {Object.entries(selectedMesh.metadata.element_types ?? {}).filter(([name]) => /line/i.test(name)).reduce((n, [,v]) => n+v,0).toLocaleString()}</span> }
              <span><strong>Size:</strong> {selectedMesh.settings.min_size ?? "?"}–{selectedMesh.settings.max_size ?? "?"}</span>
              <span><strong>Versions:</strong> {meshVersions.length}</span>
            </>
          )}
        </div>
      )}
      {viewMode === "mesh" && geometryJobId && selectedMeshJobId && (
        <MeshQualityPanel projectId={projectId} geometryJobId={geometryJobId}
          meshJobId={selectedMeshJobId} revision={meshRevision} />
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
