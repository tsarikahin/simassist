import { fetchPreview } from "./previewRequests";
import type { MeshSurfacePreview } from "./meshPreviews";

const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "http://localhost:8000";

export interface MeshVersion {
  job_id: string;
  artifact_id: string;
  created_at: string;
  settings: {
    dimension?: number;
    min_size?: number;
    max_size?: number;
    element_family?: string;
  };
  metadata: {
    node_count?: number;
    element_count?: number;
    element_types?: Record<string, number>;
    volume_element_types?: Record<string, number>;
  };
}

export async function listMeshVersions(
  projectId: string,
  geometryJobId: string,
  signal?: AbortSignal,
): Promise<MeshVersion[]> {
  const response = await fetch(
    `${API_URL}/api/projects/${projectId}/geometries/${geometryJobId}/meshes`,
    { signal },
  );
  if (!response.ok) {
    throw new Error(`Mesh versions failed: HTTP ${response.status}`);
  }
  const data: unknown = await response.json();
  if (!Array.isArray(data)) {
    throw new Error("Invalid mesh version list");
  }
  return data as MeshVersion[];
}

export async function getMeshVersionPreview(
  projectId: string,
  geometryJobId: string,
  meshJobId: string,
  signal?: AbortSignal,
): Promise<MeshSurfacePreview> {
  return await fetchPreview(
    `${API_URL}/api/projects/${projectId}/geometries/${geometryJobId}/meshes/${meshJobId}/preview`, signal,
  ) as MeshSurfacePreview;
}
