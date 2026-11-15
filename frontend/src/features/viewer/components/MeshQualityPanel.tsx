import { useEffect, useState } from "react";
import { getMeshQuality, type MeshQualityReport } from "../../../services/meshQuality";

interface Props {
  projectId: string;
  geometryJobId: string;
  meshJobId: string;
  revision: number;
}

function format(value: number | null | undefined) {
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 4 }) : "—";
}

export function MeshQualityPanel({ projectId, geometryJobId, meshJobId, revision }: Props) {
  const [report, setReport] = useState<MeshQualityReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setReport(null);
    setError(null);
    if (!meshJobId) return () => controller.abort();
    setLoading(true);
    void getMeshQuality(projectId, geometryJobId, meshJobId, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setReport(data);
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : "Quality unavailable");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [projectId, geometryJobId, meshJobId, revision]);

  const cellStyle = { display: "inline-flex", alignItems: "center", gap: 4, whiteSpace: "nowrap" } as const;
  return (
    <section aria-label="Mesh quality" style={{ padding: "8px 12px", fontSize: 12, borderTop: "1px solid #334155", background: "#0f172a", color: "#cbd5e1" }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 16 }}>
        <strong>Mesh Quality</strong>
        {loading && <span>Analyzing elements...</span>}
        {error && <span role="alert" style={{ color: "#fb7185" }}>{error}</span>}
        {report && (
          <>
            <span style={cellStyle}>Analyzed: <strong>{format(report.analyzed_element_count)}</strong></span>
            <span style={cellStyle}>Degenerate: <strong style={{ color: report.degenerate_count ? "#fb7185" : "#34d399" }}>{report.degenerate_count}</strong></span>
            {report.quality ? (
              <>
                <span style={cellStyle}>Quality min/avg: <strong>{format(report.quality.min)} / {format(report.quality.mean)}</strong></span>
                <span style={cellStyle}>Low (&lt; {report.low_quality_threshold}): <strong style={{ color: report.low_quality_count ? "#fbbf24" : "#34d399" }}>{report.low_quality_count}</strong></span>
                <span style={cellStyle}>Edge ratio avg/max: <strong>{format(report.edge_aspect_ratio?.mean)} / {format(report.edge_aspect_ratio?.max)}</strong></span>
              </>
            ) : (
              <span style={cellStyle}>Length min/avg/max: <strong>{format(report.segment_length?.min)} / {format(report.segment_length?.mean)} / {format(report.segment_length?.max)}</strong></span>
            )}
            <button type="button" aria-expanded={expanded} onClick={() => setExpanded((old) => !old)}
              style={{ padding: "3px 8px", border: "1px solid #475569", borderRadius: 4, color: "#e2e8f0", background: "#1e293b", cursor: "pointer" }}>
              {expanded ? "Hide details" : "Inspect quality"}
            </button>
          </>
        )}
      </div>
      {report && expanded && (
        <div style={{ marginTop: 10, maxHeight: 200, overflow: "auto", lineHeight: 1.6 }}>
          <div><strong>Metric:</strong> {report.quality_method}</div>
          <div><strong>Element families:</strong> {Object.entries(report.element_families).map(([name, count]) => `${name}: ${count}`).join(", ")}</div>
          <div><strong>Worst elements</strong> (analysis-local indices; not Gmsh tags)</div>
          {report.worst_elements.length === 0 ? <div>No low-quality elements found.</div> : (
            <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
              {report.worst_elements.map((element) => (
                <span key={element.index} style={{ border: "1px solid #334155", padding: "3px 6px", borderRadius: 4 }}>
                  #{element.index} · {element.family} · {report.dimension === 1 ? `length ${format(element.length)}` : `q ${format(element.quality)} · ratio ${format(element.edge_aspect_ratio)}`}
                </span>
              ))}
            </div>
          )}
          <div style={{ opacity: 0.65, marginTop: 4 }}>{report.limitations}</div>
        </div>
      )}
    </section>
  );
}
