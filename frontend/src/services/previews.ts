
const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface GeometryPreview {
  points: [number, number, number][];
  triangles: [number, number, number][];
  point_count: number;
  triangle_count: number;
}

export async function getGeometryPreview(
  projectId: string,
  artifactId: string,
  signal?: AbortSignal,
): Promise<GeometryPreview> {
  const url =
    `${API_URL}/api/projects/${projectId}` +
    `/artifacts/${artifactId}/download`;

  const response = await fetch(url, { signal });

  if (!response.ok) {
    throw new Error(
      `Preview download failed: HTTP ${response.status}`,
    );
  }

  const data: unknown = await response.json();

  if (
    !data ||
    typeof data !== "object" ||
    !("points" in data) ||
    !("triangles" in data) ||
    !Array.isArray(data.points) ||
    !Array.isArray(data.triangles)
  ) {
    throw new Error("Invalid geometry preview format");
  }

  const preview = data as GeometryPreview;

  if (
    preview.points.some(
      (point) =>
        !Array.isArray(point) ||
        point.length !== 3 ||
        point.some(
          (value) =>
            typeof value !== "number" ||
            !Number.isFinite(value),
        ),
    ) ||
    preview.triangles.some(
      (triangle) =>
        !Array.isArray(triangle) ||
        triangle.length !== 3 ||
        triangle.some(
          (index) =>
            !Number.isInteger(index) ||
            index < 0 ||
            index >= preview.points.length,
        ),
    )
  ) {
    throw new Error("Invalid geometry coordinates or triangles");
  }

  return preview;
}
