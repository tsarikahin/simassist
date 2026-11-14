
import { useEffect, useRef } from "react";
import { Maximize2, RotateCcw } from "lucide-react";

import "@kitware/vtk.js/Rendering/Profiles/All";

import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";

type VtkInstance = ReturnType<
  typeof vtkGenericRenderWindow.newInstance
>;

export function SimulationViewer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const vtkRef = useRef<VtkInstance | null>(null);

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

  function resetCamera() {
    const vtk = vtkRef.current;
    if (!vtk) return;

    vtk.getRenderer().resetCamera();
    vtk.getRenderWindow().render();
  }

  function fullscreen() {
    void containerRef.current?.requestFullscreen();
  }

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

        <div className="viewer-empty-state">
          <h3>No geometry loaded</h3>
          <p>
            Create or import a geometry to display it here.
          </p>
        </div>
      </div>

      <div className="viewer-footer">
        <span>Geometry: None</span>
        <span>Units: Not specified</span>
      </div>
    </div>
  );
}
