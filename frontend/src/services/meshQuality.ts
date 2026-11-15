const API_URL =
  import.meta.env.VITE_API_URL ??
  import.meta.env.VITE_API_BASE_URL ??
  "http://localhost:8000";

export interface MetricStats {
  min: number;
  mean: number;
  max: number;
}

export interface WorstElement {
  index: number;
  family: string;
  quality: number | null;
  edge_aspect_ratio: number | null;
  length: number | null;
}

export interface MeshQualityReport {
  mesh_job_id: string;
  mesh_artifact_id: string;
  dimension: number;
  node_count: number;
  analyzed_element_count: number;
  element_families: Record<string, number>;
  quality_method: string;
  low_quality_threshold: number | null;
  low_quality_count: number;
  degenerate_count: number;
  quality: MetricStats | null;
  edge_aspect_ratio: MetricStats | null;
  segment_length: MetricStats | null;
  worst_elements: WorstElement[];
  limitations: string;
}

export async function getMeshQuality(
  projectId: string,
  geometryJobId: string,
  meshJobId: string,
  signal?: AbortSignal,
): Promise<MeshQualityReport> {
  const response = await fetch(
    `${API_URL}/api/projects/${projectId}/geometries/${geometryJobId}/meshes/${meshJobId}/quality`,
    { signal },
  );
  if (!response.ok) {
    throw new Error(`Mesh quality request failed: HTTP ${response.status}`);
  }
  return (await response.json()) as MeshQualityReport;
}
