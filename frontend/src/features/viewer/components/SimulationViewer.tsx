
import { useEffect, useRef, useState } from "react";
import { Maximize2, RotateCcw } from "lucide-react";

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

  polyData.getPolys().setData(cells);

  return polyData;
}

export function SimulationViewer({
  projectId,
  previewArtifactId,
}: SimulationViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const vtkRef = useRef<VtkInstance | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [geometry, setGeometry] = useState<{
    artifactId: string;
    pointCount: number;
    triangleCount: number;
  } | null>(null);

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

    if (!previewArtifactId) {
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
        const preview = await getGeometryPreview(
          projectId,
          previewArtifactId!,
          controller.signal,
        );

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
          artifactId: previewArtifactId!,
          pointCount: preview.point_count,
          triangleCount: preview.triangle_count,
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
  }, [projectId, previewArtifactId]);

  function resetCamera() {
    vtkRef.current?.getRenderer().resetCamera();
    vtkRef.current?.getRenderWindow().render();
  }

  function fullscreen() {
    void containerRef.current?.requestFullscreen();
  }

  const currentGeometry =
    geometry?.artifactId === previewArtifactId
      ? geometry
      : null;

  return (
    <div className="simulation-viewer">
      <div className="viewer-toolbar">
        <span>3D Viewport</span>

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

        {!previewArtifactId && (
          <div className="viewer-empty-state">
            <h3>No geometry loaded</h3>
            <p>Create or import a geometry to get started.</p>
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

      <div className="viewer-footer">
        <span>
          {currentGeometry
            ? `Points: ${currentGeometry.pointCount}`
            : "Geometry: None"}
        </span>
        <span>
          {currentGeometry
            ? `Triangles: ${currentGeometry.triangleCount}`
            : "Units: Not specified"}
        </span>
      </div>
    </div>
  );
}
