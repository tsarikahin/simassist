export type EntityDimension = 0 | 1 | 2 | 3;

export interface CadEntity {
  geometry_revision_id: string;
  entity_id: string;
  entity_key: string;
  dimension: EntityDimension;
  tag: number;
  label: string;
  geometric_type: string;
  coordinate_units: string;
  bounds: [number, number, number, number, number, number];
  coordinates: [number, number, number] | null;
  length: number | null;
  area: number | null;
  volume: number | null;
  measure_units: string | null;
  normal: [number, number, number] | null;
  normal_information: string | null;
  boundary_entity_keys: string[];
  owner_body_keys: string[];
}

interface EntitySelection {
  ok: boolean;
  selection: CadEntity | null;
  clarification_required: boolean;
}

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function geometrySelection(
  project: string,
  signal?: AbortSignal,
  change?: { geometry_revision_id: string; dimension: EntityDimension | null; tag: number | null },
): Promise<EntitySelection> {
  const response = await fetch(`${API_URL}/api/projects/${project}/geometry-selection`, {
    method: change ? "PUT" : "GET",
    headers: change ? { "Content-Type": "application/json" } : undefined,
    body: change ? JSON.stringify(change) : undefined,
    signal,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail ?? `Geometry selection unavailable: HTTP ${response.status}`);
  }
  return response.json();
}
