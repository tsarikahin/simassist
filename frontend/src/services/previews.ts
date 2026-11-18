import { fetchPreview } from "./previewRequests";
import type { CadFace } from "./cadFaces";
import type { CadEntity } from "./cadEntities";

const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface GeometryPreview {
  points: [number, number, number][];
  triangles: [number, number, number][];
  lines?: [number, number][];
  quads?: [number, number, number, number][];
  dimension?: number;
  line_count?: number;
  quad_count?: number;
  point_count: number;
  triangle_count: number;
  geometry_revision_id?: string;
  triangle_face_keys?: string[];
  faces?: CadFace[];
  topology_version?: number;
  entities?: CadEntity[];
  vertex_point_indices?: number[];
  vertex_entity_keys?: string[];
  edge_segments?: [number, number][];
  edge_entity_keys?: string[];
}

export async function getGeometryPreview(
  projectId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<GeometryPreview> {
  const url =
    `${API_URL}/api/projects/${projectId}` +
    `/cad-previews/${artifactId}`;

  return fetchPreview(url, signal);
}
