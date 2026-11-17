export interface CadFace {
  geometry_revision_id: string;
  face_key: string;
  local_gmsh_tag: number;
  area: number;
  coordinate_units: string;
  area_units: string;
  bounds: [number, number, number, number, number, number];
  geometric_type: string;
  normal: [number, number, number] | null;
  normal_information: string;
}

export interface CadSelection {
  ok: boolean;
  selection: CadFace | null;
  clarification_required: boolean;
}

const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export async function cadSelection(
  project: string,
  signal?: AbortSignal,
  change?: { geometry_revision_id: string; face_key: string | null },
): Promise<CadSelection> {
  const response = await fetch(`${API_URL}/api/projects/${project}/cad-selection`, {
    method: change ? "PUT" : "GET",
    headers: change ? { "Content-Type": "application/json" } : undefined,
    body: change ? JSON.stringify(change) : undefined,
    signal,
  });
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail ?? `CAD selection unavailable: HTTP ${response.status}`);
  }
  return response.json();
}
