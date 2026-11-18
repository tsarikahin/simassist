import vtkGenericRenderWindow from "@kitware/vtk.js/Rendering/Misc/GenericRenderWindow";
import vtkActor from "@kitware/vtk.js/Rendering/Core/Actor";
import vtkMapper from "@kitware/vtk.js/Rendering/Core/Mapper";
import vtkCellPicker from "@kitware/vtk.js/Rendering/Core/CellPicker";
import vtkPointPicker from "@kitware/vtk.js/Rendering/Core/PointPicker";
import vtkDataArray from "@kitware/vtk.js/Common/Core/DataArray";
import type vtkCamera from "@kitware/vtk.js/Rendering/Core/Camera";
import vtkPolyData from "@kitware/vtk.js/Common/DataModel/PolyData";
import vtkAxesActor from "@kitware/vtk.js/Rendering/Core/AxesActor";
import vtkOrientationMarkerWidget from "@kitware/vtk.js/Interaction/Widgets/OrientationMarkerWidget";
import type { GeometryPreview } from "../../../services/previews";
import type { CadEntity, EntityDimension } from "../../../services/cadEntities";
import { resolveCadPick, selectionLimitation } from "./cadPicking";
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
  preview: GeometryPreview;
  colors?: ReturnType<typeof vtkDataArray.newInstance>;
  selected?: string | null;
  hovered?: string | null;
  camera?: Snapshot;
  vertices?: PickLayer;
  edges?: PickLayer;
};
type PickLayer = {
  actor: ReturnType<typeof vtkActor.newInstance>;
  mapper: ReturnType<typeof vtkMapper.newInstance>;
  data: ReturnType<typeof vtkPolyData.newInstance>;
  colors: ReturnType<typeof vtkDataArray.newInstance>;
  keys: string[];
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

function pickingLayer(preview: GeometryPreview, dimension: 0 | 1): PickLayer | undefined {
  const keys = dimension === 0 ? preview.vertex_entity_keys : preview.edge_entity_keys;
  if (!keys?.length) return undefined;
  const data = vtkPolyData.newInstance();
  const points = dimension === 0 ? preview.vertex_point_indices!.map(index => preview.points[index]) : preview.points;
  data.getPoints().setData(new Float32Array(points.flat()), 3);
  if (dimension === 0) {
    data.getVerts().setData(new Uint32Array(keys.flatMap((_, index) => [1, index])));
  } else {
    data.getLines().setData(new Uint32Array(preview.edge_segments!.flatMap(segment => [2, ...segment])));
  }
  const colors = vtkDataArray.newInstance({ name: "CAD entity colors", numberOfComponents: 3, values: new Uint8Array(keys.length * 3) });
  data.getCellData().setScalars(colors);
  const mapper = vtkMapper.newInstance();
  mapper.setInputData(data);
  mapper.setScalarModeToUseCellData();
  mapper.setColorModeToDirectScalars();
  mapper.setScalarVisibility(true);
  const actor = vtkActor.newInstance();
  actor.setMapper(mapper);
  actor.getProperty().setPointSize(9);
  actor.getProperty().setLineWidth(3);
  actor.getProperty().setAmbient(1);
  actor.getProperty().setDiffuse(0);
  return { actor, mapper, data, colors, keys };
}

export class ViewerScene {
  readonly window = vtkGenericRenderWindow.newInstance({
    background: [0.043, 0.071, 0.125],
  });
  private readonly axes = vtkAxesActor.newInstance({
    pickable: false,
    // Configure at construction: setters schedule an update that can outlive
    // React Strict Mode's initial mount/cleanup cycle.
    ...{
      config: { recenter: false, tipResolution: 16, shaftResolution: 12 },
      xConfig: { color: [239, 68, 68] },
      yConfig: { color: [34, 197, 94] },
      zConfig: { color: [59, 130, 246] },
    },
  });
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
  private hoverRequest = 0;
  private readonly picker = vtkCellPicker.newInstance({ tolerance: 0.0001 });
  private readonly pointPicker = vtkPointPicker.newInstance();
  private readonly occlusionPicker = vtkCellPicker.newInstance({ tolerance: 0.0001 });
  private selectionDimension: EntityDimension = 2;
  onEntityPicked?: (revision: string, entity: CadEntity | null) => void;
  onSelectionUnavailable?: (message: string) => void;
  onFacePicked?: (revision: string, faceKey: string | null) => void;
  private press: { x: number; y: number; dragged: boolean } | null = null;

  private pickFace(event: PointerEvent): string | null {
    const entry = this.datasets.get(this.active);
    if (!entry?.colors) return null;
    const rect = this.container.getBoundingClientRect();
    const [width, height] = this.window.getApiSpecificRenderWindow().getSize();
    this.picker.setTolerance(0.0001);
    this.picker.initializePickList();
    this.picker.addPickList(entry.actor);
    this.picker.setPickFromList(true);
    this.picker.pick([
      (event.clientX - rect.left) * width / rect.width,
      (rect.bottom - event.clientY) * height / rect.height,
      0,
    ], this.window.getRenderer());
    const cell = this.picker.getCellId() - (entry.preview.lines?.length ?? 0);
    return cell >= 0 ? entry.preview.triangle_face_keys?.[cell] ?? null : null;
  }
  private pickEntity(event: PointerEvent) {
    const entry = this.datasets.get(this.active);
    if (!entry) return { entity: null, issue: null };
    const issue = selectionLimitation(entry.preview, this.selectionDimension);
    if (issue) return { entity: null, issue };
    if (this.selectionDimension >= 2) {
      return resolveCadPick(entry.preview, this.selectionDimension, this.pickFace(event));
    }
    const layer = this.selectionDimension === 0 ? entry.vertices : entry.edges;
    if (!layer) return { entity: null, issue: "No CAD picking layer is available for this entity type." };
    const rect = this.container.getBoundingClientRect();
    const view = this.window.getApiSpecificRenderWindow();
    const [width, height] = view.getSize();
    const picker = this.selectionDimension === 0 ? this.pointPicker : this.picker;
    picker.setTolerance(6 / Math.hypot(rect.width, rect.height));
    picker.initializePickList();
    picker.addPickList(layer.actor);
    picker.setPickFromList(true);
    picker.pick([(event.clientX - rect.left) * width / rect.width, (rect.bottom - event.clientY) * height / rect.height, 0], this.window.getRenderer());
    const index = !picker.getActors().length ? -1 : this.selectionDimension === 0 ? this.pointPicker.getPointId() : this.picker.getCellId();
    const key = layer.keys[index] ?? null;
    if (key && entry.preview.triangles.length) {
      const position = this.selectionDimension === 0
        ? entry.preview.points[entry.preview.vertex_point_indices![index]] : picker.getPickPosition();
      const screen = view.worldToDisplay(position[0], position[1], position[2], this.window.getRenderer());
      this.occlusionPicker.initializePickList();
      this.occlusionPicker.addPickList(entry.actor);
      this.occlusionPicker.setPickFromList(true);
      this.occlusionPicker.pick([screen[0], screen[1], 0], this.window.getRenderer());
      if (this.occlusionPicker.getCellId() >= 0) {
        const front = this.occlusionPicker.getPickPosition();
        const depth = view.worldToDisplay(front[0], front[1], front[2], this.window.getRenderer())[2];
        if (screen[2] > depth + 1e-5) return { entity: null, issue: "This CAD entity is occluded by a surface. Rotate the geometry to expose it before selecting." };
      }
    }
    return resolveCadPick(entry.preview, this.selectionDimension, key, index);
  }
  private pointerDown = (event: PointerEvent) => {
    if (event.button === 0) {
      this.container.focus({ preventScroll: true });
      this.press = { x: event.clientX, y: event.clientY, dragged: false };
    }
  };
  private pointerMove = (event: PointerEvent) => {
    if (this.press && Math.hypot(event.clientX - this.press.x, event.clientY - this.press.y) > 4)
      this.press.dragged = true;
    cancelAnimationFrame(this.hoverRequest);
    if (event.buttons) return;
    this.hoverRequest = requestAnimationFrame(() => {
      const entry = this.datasets.get(this.active);
      if (!entry?.preview.geometry_revision_id) return;
      const picked = this.pickEntity(event);
      const key = picked.entity?.entity_key ?? null;
      if (entry.hovered === key) return;
      entry.hovered = key;
      this.container.style.cursor = key ? "pointer" : "";
      this.colorFaces(entry);
    });
  };
  private pointerUp = (event: PointerEvent) => {
    const press = this.press;
    this.press = null;
    const entry = this.datasets.get(this.active);
    if (!press || press.dragged || event.button !== 0 || !entry?.preview.geometry_revision_id ||
        Math.hypot(event.clientX - press.x, event.clientY - press.y) > 4) return;
    const picked = this.pickEntity(event);
    if (picked.issue) { this.onSelectionUnavailable?.(picked.issue); return; }
    this.onEntityPicked?.(entry.preview.geometry_revision_id, picked.entity);
    if (this.selectionDimension === 2) this.onFacePicked?.(entry.preview.geometry_revision_id, picked.entity?.entity_key ?? null);
  };
  private pointerLeave = () => {
    cancelAnimationFrame(this.hoverRequest);
    this.press = null;
    this.container.style.cursor = "";
    const entry = this.datasets.get(this.active);
    if (entry?.hovered) { entry.hovered = null; this.colorFaces(entry); }
  };
  private keyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      const entry = this.datasets.get(this.active);
      if (entry?.preview.geometry_revision_id) {
        this.onEntityPicked?.(entry.preview.geometry_revision_id, null);
        this.onFacePicked?.(entry.preview.geometry_revision_id, null);
      }
    }
  };
  selectFace(revision: string, key: string | null) {
    this.selectEntity(revision, key);
  }
  selectEntity(revision: string, key: string | null) {
    this.datasets.forEach((entry) => {
      if (entry.preview.geometry_revision_id === revision) {
        entry.selected = key;
        this.colorFaces(entry);
      }
    });
  }
  private colorFaces(entry: Dataset) {
    if (entry.colors) {
      const colors = entry.colors.getData();
      const faces = new Map(entry.preview.entities?.filter(entity => entity.dimension === 2).map(entity => [entity.entity_key, entity]));
      entry.preview.triangle_face_keys!.forEach((key, index) => {
        const owners = faces.get(key)?.owner_body_keys ?? [];
        const selected = key === entry.selected || owners.includes(entry.selected ?? "");
        const hovered = key === entry.hovered || owners.includes(entry.hovered ?? "");
        colors.set(selected ? [255, 174, 46] : hovered ? [102, 224, 216] : [89, 166, 242], index * 3);
      });
      entry.colors.modified();
    }
    for (const [dimension, layer] of [[0, entry.vertices], [1, entry.edges]] as const) {
      if (!layer) continue;
      layer.keys.forEach((key, index) => layer.colors.getData().set(key === entry.selected ? [255, 174, 46] : key === entry.hovered ? [102, 224, 216] : [190, 205, 230], index * 3));
      layer.colors.modified();
      layer.actor.setVisibility(this.selectionDimension === dimension || layer.keys.includes(entry.selected ?? ""));
    }
    viewerMetric({ kind: "cad-highlight", face_key: entry.selected ?? null,
      hovered: entry.hovered ?? null,
      triangle_count: entry.preview.triangle_face_keys?.filter(key => key === entry.selected).length ?? 0 });
    this.render();
  }

  setSelectionMode(dimension: EntityDimension) {
    this.selectionDimension = dimension;
    const entry = this.datasets.get(this.active);
    if (entry) { entry.hovered = null; this.colorFaces(entry); }
  }

  private container: HTMLDivElement;
  private labels: HTMLDivElement;
  constructor(container: HTMLDivElement, labels: HTMLDivElement) {
    this.container = container;
    this.labels = labels;
    this.window.setContainer(container);
    container.addEventListener("pointerdown", this.pointerDown);
    container.addEventListener("pointermove", this.pointerMove);
    container.addEventListener("pointerup", this.pointerUp);
    container.addEventListener("pointerleave", this.pointerLeave);
    container.addEventListener("keydown", this.keyDown);
    this.window.resize();
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
    this.pointerLeave();
    const entry = this.datasets.get(this.active);
    if (entry) {
      entry.camera = snapshot(this.window.getRenderer().getActiveCamera());
      this.window.getRenderer().removeActor(entry.actor);
      if (entry.vertices) this.window.getRenderer().removeActor(entry.vertices.actor);
      if (entry.edges) this.window.getRenderer().removeActor(entry.edges.actor);
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
        preview,
        vertices: pickingLayer(preview, 0),
        edges: pickingLayer(preview, 1),
      };
      if (preview.geometry_revision_id && preview.triangle_face_keys?.length === preview.triangles.length && preview.faces?.length && !(preview.lines?.length)) {
        entry.colors = vtkDataArray.newInstance({ name: "CAD face colors", numberOfComponents: 3,
          values: new Uint8Array(preview.triangles.length * 3) });
        data.getCellData().setScalars(entry.colors);
        mapper.setScalarModeToUseCellData();
        mapper.setColorModeToDirectScalars();
        mapper.setScalarVisibility(true);
      }
      this.datasets.set(key, entry);
    } else {
      this.datasets.delete(key);
      this.datasets.set(key, entry);
    }
    this.active = key;
    this.window.getRenderer().addActor(entry.actor);
    if (entry.vertices) this.window.getRenderer().addActor(entry.vertices.actor);
    if (entry.edges) this.window.getRenderer().addActor(entry.edges.actor);
    const allocated = performance.now();
    if (entry.camera)
      restore(this.window.getRenderer().getActiveCamera(), entry.camera);
    else this.reset();
    this.edges(edges);
    this.colorFaces(entry);
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
    for (const layer of [entry.vertices, entry.edges]) {
      layer?.colors.delete();
      layer?.actor.delete();
      layer?.mapper.delete();
      layer?.data.delete();
    }
    entry.colors?.delete();
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
    cancelAnimationFrame(this.hoverRequest);
    this.container.removeEventListener("pointerdown", this.pointerDown);
    this.container.removeEventListener("pointermove", this.pointerMove);
    this.container.removeEventListener("pointerup", this.pointerUp);
    this.container.removeEventListener("pointerleave", this.pointerLeave);
    this.container.removeEventListener("keydown", this.keyDown);
    this.picker.delete();
    this.pointPicker.delete();
    this.occlusionPicker.delete();
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
