import type { GeometryPreview } from "./previews";

// Immutable, project-scoped URL keys. Bound memory; errors and aborted loads are never cached.
const previews = new Map<string, { data: GeometryPreview; bytes: number }>();
const LIMIT = 32 * 1024 * 1024;
let retained = 0;

export function viewerMetric(detail: Record<string, unknown>) {
  if (new URLSearchParams(location.search).has("viewerDebug")) {
    window.dispatchEvent(
      new CustomEvent("simassist:viewer-performance", { detail }),
    );
  }
}

export async function fetchPreview(
  url: string,
  signal?: AbortSignal,
): Promise<GeometryPreview> {
  signal?.throwIfAborted();
  const cached = previews.get(url);
  if (cached) {
    previews.delete(url);
    previews.set(url, cached);
    viewerMetric({
      kind: "preview",
      url,
      browser_cache: true,
      transfer_ms: 0,
      parse_ms: 0,
      validation_ms: 0,
    });
    return cached.data;
  }
  const started = performance.now();
  const response = await fetch(url, { signal });
  if (!response.ok)
    throw new Error(`Preview unavailable: HTTP ${response.status}`);
  const headersAt = performance.now();
  const text = await response.text();
  const transferredAt = performance.now();
  const data = JSON.parse(text) as GeometryPreview;
  const parsedAt = performance.now();
  if (!data || !Array.isArray(data.points) || !Array.isArray(data.triangles))
    throw new Error("Invalid preview format");
  const points = data.points;
  if (
    points.some(
      (p) =>
        !Array.isArray(p) ||
        p.length !== 3 ||
        p.some((v) => !Number.isFinite(v)),
    )
  )
    throw new Error("Invalid preview coordinates");
  for (const [cells, width] of [
    [data.triangles, 3],
    [data.quads ?? [], 4],
    [data.lines ?? [], 2],
  ] as const) {
    if (
      !Array.isArray(cells) ||
      cells.some(
        (cell) =>
          !Array.isArray(cell) ||
          cell.length !== width ||
          cell.some((i) => !Number.isInteger(i) || i < 0 || i >= points.length),
      )
    )
      throw new Error("Invalid preview cell connectivity");
  }
  if (
    data.point_count !== points.length ||
    data.triangle_count !== data.triangles.length
  )
    throw new Error("Preview count mismatch");
  signal?.throwIfAborted();
  const bytes =
    text.length * 2 +
    data.points.length * 96 +
    data.triangles.length * 96 +
    (data.quads?.length ?? 0) * 112 +
    (data.lines?.length ?? 0) * 80; // Estimated nested-array storage; GPU buffers are separate.
  if (bytes <= LIMIT) {
    while (retained + bytes > LIMIT && previews.size) {
      const key = previews.keys().next().value!;
      retained -= previews.get(key)!.bytes;
      previews.delete(key);
    }
    previews.set(url, { data, bytes });
    retained += bytes;
  }
  viewerMetric({
    kind: "preview",
    url,
    browser_cache: false,
    headers_ms: headersAt - started,
    transfer_ms: transferredAt - headersAt,
    parse_ms: parsedAt - transferredAt,
    validation_ms: performance.now() - parsedAt,
    response_bytes: text.length,
    server_timing: response.headers.get("Server-Timing"),
    backend_cache: response.headers.get("X-Preview-Cache"),
  });
  return data;
}
