import type { GeometryPreview } from "./previews";

const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "http://localhost:8000";

export interface MeshSurfacePreview extends GeometryPreview {
  mesh_job_id: string;
  mesh_artifact_id: string;
  volume_element_count: number;
  dimension?: number;
  line_count?: number;
  quad_count?: number;
  source_node_count: number;
}

export async function getLatestMeshPreview(
  projectId: string,
  geometryJobId: string,
  signal?: AbortSignal,
): Promise<MeshSurfacePreview> {
  const url =
    `${API_URL}/api/projects/${projectId}` +
    `/geometries/${geometryJobId}/mesh-preview`;
  const response = await fetch(url, { signal });
  if (!response.ok) {
    if (response.status === 404) {
      throw new Error("No completed mesh found for this geometry.");
    }
    throw new Error(`Mesh preview failed: HTTP ${response.status}`);
  }
  const data: unknown = await response.json();
  if (!data || typeof data !== "object") {
    throw new Error("Invalid mesh preview response");
  }
  const parsed = data as Partial<MeshSurfacePreview>;
  if (!Array.isArray(parsed.points) || !Array.isArray(parsed.triangles)) {
    throw new Error("Mesh preview is missing coordinates or surface triangles");
  }
  if (
    parsed.points.some(
      (p) => !Array.isArray(p) || p.length !== 3 ||
        p.some((v) => typeof v !== "number" || !Number.isFinite(v)),
    ) ||
    parsed.triangles.some(
      (t) => !Array.isArray(t) || t.length !== 3 ||
        t.some((i) => !Number.isInteger(i) || i < 0 || i >= parsed.points!.length),
    )
  ) {
    throw new Error("Invalid mesh surface coordinates");
  }
  return parsed as MeshSurfacePreview;
}
