import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import type vtkCamera from "@kitware/vtk.js/Rendering/Core/Camera";
import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";
import vtkAxesActor from "@kitware/vtk.js/Rendering/Core/AxesActor";
import vtkOrientationMarkerWidget from "@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget";
import type { GeometryPreview } from "../../../services/previews";
import { viewerMetric } from "../../../services/previewRequests";
import "@kitware/vtk.js/Rendering/Profiles/Geometry";

type Camera = vtkCamera;
type Snapshot = {
  position: number[];
  focal: number[];
  up: number[];
  parallel: boolean;
  scale: number;
};
type Dataset = {
  actor: ReturnType<typeof vtkActor.newInstance>;
  mapper: ReturnType<typeof vtkMapper.newInstance>;
  data: ReturnType<typeof vtkPolyData.newInstance>;
  preview: Pick<GeometryPreview, "dimension">;
  camera?: Snapshot;
};
export type StandardView = "+X" | "-X" | "+Y" | "-Y" | "+Z" | "-Z";

function snapshot(camera: Camera): Snapshot {
  return {
    position: [...camera.getPosition()],
    focal: [...camera.getFocalPoint()],
    up: [...camera.getViewUp()],
    parallel: camera.getParallelProjection(),
    scale: camera.getParallelScale(),
  };
}
function restore(camera: Camera, state: Snapshot) {
  camera.setPosition(state.position[0], state.position[1], state.position[2]);
  camera.setFocalPoint(state.focal[0], state.focal[1], state.focal[2]);
  camera.setViewUp(state.up[0], state.up[1], state.up[2]);
  camera.setParallelProjection(state.parallel);
  camera.setParallelScale(state.scale);
}
function polyData(preview: GeometryPreview) {
  const data = vtkPolyData.newInstance();
  const points = new Float32Array(preview.points.length * 3);
  preview.points.forEach((p, i) => points.set(p, i * 3));
  data.getPoints().setData(points, 3);
  const cells = new Uint32Array(
    preview.triangles.length * 4 + (preview.quads?.length ?? 0) * 5,
  );
  let offset = 0;
  for (const cell of [...preview.triangles, ...(preview.quads ?? [])]) {
    cells[offset++] = cell.length;
    cells.set(cell, offset);
    offset += cell.length;
  }
  data.getPolys().setData(cells);
  const lines = new Uint32Array((preview.lines?.length ?? 0) * 3);
  (preview.lines ?? []).forEach((p, i) => {
    lines[i * 3] = 2;
    lines.set(p, i * 3 + 1);
  });
  data.getLines().setData(lines);
  return data;
}

export class ViewerScene {
  readonly window = vtkGenericRenderWindow.newInstance({
    background: [0.043, 0.071, 0.125],
  });
  private readonly axes = vtkAxesActor.newInstance();
  private readonly marker: ReturnType<
    typeof vtkOrientationMarkerWidget.newInstance
  >;
  private readonly observer: ResizeObserver;
  private readonly datasets = new Map<string, Dataset>();
  private active = "";
  private readonly subscriptions: { unsubscribe: () => void }[] = [];
  private frames = 0;
  private frameStart = 0;
  private disposed = false;
  private frameRequest = 0;

  private container: HTMLDivElement;
  private labels: HTMLDivElement;
  constructor(container: HTMLDivElement, labels: HTMLDivElement) {
    this.container = container;
    this.labels = labels;
    this.window.setContainer(container);
    this.window.resize();
    this.axes.setConfig({
      ...this.axes.getConfig(),
      recenter: false,
      tipResolution: 16,
      shaftResolution: 12,
    });
    this.axes.setXAxisColor([239, 68, 68]);
    this.axes.setYAxisColor([34, 197, 94]);
    this.axes.setZAxisColor([59, 130, 246]);
    this.axes.update();
    this.marker = vtkOrientationMarkerWidget.newInstance({
      actor: this.axes,
      interactor: this.window.getInteractor(),
      parentRenderer: this.window.getRenderer(),
      viewportSize: 0.18,
      minPixelSize: 90,
      maxPixelSize: 130,
    });
    this.marker.setEnabled(true);
    const interactor = this.window.getInteractor();
    this.subscriptions.push(
      this.window
        .getRenderer()
        .getActiveCamera()
        .onModified(() => this.updateLabels())!,
    );
    this.subscriptions.push(
      interactor.onStartAnimation(() => {
        this.frames = 0;
        this.frameStart = performance.now();
      }),
    );
    this.subscriptions.push(
      interactor.onAnimation(() => {
        this.frames++;
      }),
    );
    this.subscriptions.push(
      interactor.onEndAnimation(() => {
        const elapsed = performance.now() - this.frameStart;
        viewerMetric({
          kind: "interaction",
          frames: this.frames,
          elapsed_ms: elapsed,
          fps:
            elapsed >= 1000 ? interactor.getRecentAnimationFrameRate() : null,
          fps_kind: "vtk_animation_estimate",
          animation_event_rate: elapsed ? (this.frames * 1000) / elapsed : 0,
        });
        this.cameraMetric();
      }),
    );
    this.observer = new ResizeObserver(() => {
      this.window.resize();
      this.marker.updateViewport();
      this.updateLabels();
      this.render();
    });
    this.observer.observe(container);
  }
  private updateLabels() {
    if (this.disposed) return;
    this.marker.updateMarkerOrientation();
    const view = this.window.getApiSpecificRenderWindow();
    const [width, height] = view.getSize();
    if (!width || !height) return;
    const endpoints = [
      [1.16, 0, 0],
      [0, 1.16, 0],
      [0, 0, 1.16],
    ];
    endpoints.forEach((p, i) => {
      const screen = view.worldToDisplay(
        p[0],
        p[1],
        p[2],
        this.marker.getRenderer(),
      );
      const label = this.labels.children[i] as HTMLElement;
      label.style.transform = `translate(${(screen[0] * this.container.clientWidth) / width}px,${((height - screen[1]) * this.container.clientHeight) / height}px) translate(-50%,-50%)`;
    });
  }
  private cameraMetric() {
    const camera = this.window.getRenderer().getActiveCamera();
    viewerMetric({
      kind: "camera",
      key: this.active,
      position: camera.getPosition(),
      focal: camera.getFocalPoint(),
      up: camera.getViewUp(),
      direction: camera.getDirectionOfProjection(),
      triad_direction: this.marker
        .getRenderer()
        .getActiveCamera()
        .getDirectionOfProjection(),
      parallel: camera.getParallelProjection(),
    });
  }
  private render() {
    this.window.getRenderer().resetCameraClippingRange();
    this.updateLabels();
    this.window.getRenderWindow().render();
  }
  hide() {
    const entry = this.datasets.get(this.active);
    if (entry) {
      entry.camera = snapshot(this.window.getRenderer().getActiveCamera());
      this.window.getRenderer().removeActor(entry.actor);
    }
    this.active = "";
    this.render();
  }
  show(preview: GeometryPreview, key: string, edges: boolean) {
    const started = performance.now();
    if (key === this.active) return;
    this.hide();
    let entry = this.datasets.get(key);
    const reused = Boolean(entry);
    if (!entry) {
      const data = polyData(preview),
        mapper = vtkMapper.newInstance(),
        actor = vtkActor.newInstance();
      mapper.setInputData(data);
      actor.setMapper(mapper);
      const property = actor.getProperty();
      property.setColor(0.35, 0.65, 0.95);
      property.setAmbient(0.25);
      property.setDiffuse(0.75);
      property.setSpecular(0.3);
      property.setSpecularPower(25);
      property.setInterpolationToPhong();
      property.setEdgeColor(0.05, 0.13, 0.22);
      property.setLineWidth(1);
      entry = {
        data,
        mapper,
        actor,
        preview: { dimension: preview.dimension },
      };
      this.datasets.set(key, entry);
    } else {
      this.datasets.delete(key);
      this.datasets.set(key, entry);
    }
    this.active = key;
    this.window.getRenderer().addActor(entry.actor);
    const allocated = performance.now();
    if (entry.camera)
      restore(this.window.getRenderer().getActiveCamera(), entry.camera);
    else this.reset();
    this.edges(edges);
    this.render();
    const rendered = performance.now();
    this.cameraMetric();
    viewerMetric({
      kind: "scene",
      key,
      reused,
      allocation_ms: allocated - started,
      render_submit_ms: rendered - allocated,
      points: preview.point_count,
      triangles: preview.triangle_count,
    });
    cancelAnimationFrame(this.frameRequest);
    this.frameRequest = requestAnimationFrame(() => {
      if (!this.disposed)
        viewerMetric({
          kind: "first-frame",
          key,
          elapsed_ms: performance.now() - started,
        });
    });
    while (this.datasets.size > 2) {
      const oldKey = this.datasets.keys().next().value!;
      this.disposeDataset(this.datasets.get(oldKey)!);
      this.datasets.delete(oldKey);
    }
  }
  private disposeDataset(entry: Dataset) {
    entry.actor.delete();
    entry.mapper.delete();
    entry.data.delete();
  }
  edges(visible: boolean) {
    this.datasets
      .get(this.active)
      ?.actor.getProperty()
      .setEdgeVisibility(visible);
    this.render();
  }
  projection(parallel: boolean) {
    this.window.getRenderer().getActiveCamera().setParallelProjection(parallel);
    this.fit();
  }
  isParallel() {
    return this.window.getRenderer().getActiveCamera().getParallelProjection();
  }
  fit() {
    this.window.getRenderer().resetCamera();
    this.render();
    this.cameraMetric();
  }
  standard(view: StandardView) {
    const camera = this.window.getRenderer().getActiveCamera();
    const center = camera.getFocalPoint(),
      distance = Math.max(camera.getDistance(), 1e-6);
    const index = { X: 0, Y: 1, Z: 2 }[view[1] as "X" | "Y" | "Z"];
    const position = [...center];
    position[index] += (view[0] === "+" ? 1 : -1) * distance;
    camera.setPosition(position[0], position[1], position[2]);
    const up = index === 2 ? [0, 1, 0] : [0, 0, 1];
    camera.setViewUp(up[0], up[1], up[2]);
    this.fit();
  }
  reset() {
    const entry = this.datasets.get(this.active);
    if (!entry) return;
    const renderer = this.window.getRenderer(),
      camera = renderer.getActiveCamera(),
      bounds = entry.actor.getBounds();
    const center = [
      (bounds[0] + bounds[1]) / 2,
      (bounds[2] + bounds[3]) / 2,
      (bounds[4] + bounds[5]) / 2,
    ];
    const size = Math.max(
      bounds[1] - bounds[0],
      bounds[3] - bounds[2],
      bounds[5] - bounds[4],
      1e-6,
    );
    camera.setFocalPoint(center[0], center[1], center[2]);
    const planar = (entry.preview.dimension ?? 3) <= 2;
    camera.setPosition(
      center[0] + (planar ? 0 : 1.5 * size),
      center[1] - (planar ? 0 : 1.8 * size),
      center[2] + (planar ? 2 : 1.2) * size,
    );
    const up = planar ? [0, 1, 0] : [0, 0, 1];
    camera.setViewUp(up[0], up[1], up[2]);
    camera.setParallelProjection(planar);
    this.fit();
  }
  delete() {
    this.disposed = true;
    cancelAnimationFrame(this.frameRequest);
    this.observer.disconnect();
    this.subscriptions.forEach((s) => s.unsubscribe());
    this.marker.setEnabled(false);
    this.marker.delete();
    this.axes.delete();
    this.datasets.forEach((entry) => this.disposeDataset(entry));
    this.datasets.clear();
    this.window.delete();
  }
}
