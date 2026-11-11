
import { useEffect, useRef, useState } from "react";
import { Maximize2, RotateCcw } from "lucide-react";

// Register VTK.js rendering implementations
import "@kitware/vtk.js/Rendering/Profiles/All";

import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";
import vtkCubeSource from "@kitware/vtk.js/Filters/Sources/CubeSource";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";

export function SimulationViewer() {
  const containerRef = useRef<HTMLDivElement>(null);
  const vtkRef = useRef<{
    genericRenderWindow: ReturnType<typeof vtkGenericRenderWindow.newInstance>;
    actor: ReturnType<typeof vtkActor.newInstance>;
  } | null>(null);

  const [wireframe, setWireframe] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const genericRenderWindow = vtkGenericRenderWindow.newInstance({
      background: [0.043, 0.071, 0.125],
    });

    genericRenderWindow.setContainer(container);
    genericRenderWindow.resize();

    const renderer = genericRenderWindow.getRenderer();
    const renderWindow = genericRenderWindow.getRenderWindow();

    const cubeSource = vtkCubeSource.newInstance({
      xLength: 100,
      yLength: 20,
      zLength: 10,
      center: [50, 0, 0],
    });

    const mapper = vtkMapper.newInstance();
    mapper.setInputConnection(cubeSource.getOutputPort());

    const actor = vtkActor.newInstance();
    actor.setMapper(mapper);
    actor.getProperty().setColor(0.35, 0.65, 0.95);
    actor.getProperty().setEdgeVisibility(true);
    actor.getProperty().setEdgeColor(0.12, 0.2, 0.35);

    renderer.addActor(actor);
    renderer.resetCamera();
    renderWindow.render();

    vtkRef.current = { genericRenderWindow, actor };

    const resizeObserver = new ResizeObserver(() => {
      genericRenderWindow.resize();
      renderWindow.render();
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      vtkRef.current = null;

      actor.delete();
      mapper.delete();
      cubeSource.delete();
      genericRenderWindow.delete();
    };
  }, []);

  function resetCamera() {
    const vtk = vtkRef.current;
    if (!vtk) return;

    vtk.genericRenderWindow.getRenderer().resetCamera();
    vtk.genericRenderWindow.getRenderWindow().render();
  }

  function toggleWireframe() {
    const vtk = vtkRef.current;
    if (!vtk) return;

    const next = !wireframe;
    setWireframe(next);

    const property = vtk.actor.getProperty();

    if (next) {
      property.setRepresentationToWireframe();
    } else {
      property.setRepresentationToSurface();
    }

    vtk.genericRenderWindow.getRenderWindow().render();
  }

  return (
    <div className="simulation-viewer">
      <div className="viewer-toolbar">
        <span>Perspective · Cantilever Beam</span>

        <div className="viewer-tools">
          <button
            type="button"
            onClick={toggleWireframe}
            title="Toggle wireframe"
          >
            {wireframe ? "Solid" : "Wireframe"}
          </button>

          <button
            type="button"
            onClick={resetCamera}
            title="Reset camera"
          >
            <RotateCcw size={17} />
          </button>

          <button
            type="button"
            onClick={() =>
              containerRef.current?.requestFullscreen()
            }
            title="Fullscreen"
          >
            <Maximize2 size={17} />
          </button>
        </div>
      </div>

      <div ref={containerRef} className="vtk-container" />

      <div className="viewer-footer">
        <span>Geometry: 100 × 20 × 10 mm</span>
        <span>Units: mm, N, MPa</span>
      </div>
    </div>
  );
}
