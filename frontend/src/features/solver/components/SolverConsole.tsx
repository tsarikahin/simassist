
import { useEffect, useState } from "react";
import { Terminal } from "lucide-react";

import { getJob, type Job } from "../../../services/jobs";

interface SolverConsoleProps {
  jobId: string | null;
  onPreviewReady: (artifactId: string) => void;
}

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
]);

export function SolverConsole({
  jobId,
  onPreviewReady,
}: SolverConsoleProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    let active = true;
    let inFlight = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    async function refresh() {
      if (!active || inFlight) return;

      inFlight = true;

      try {
        const updated = await getJob(jobId!);

        if (!active) return;

        setJob(updated);
        setError(null);

        if (updated.status === "completed") {
          const previewId =
            updated.result?.preview_artifact_id;

          if (typeof previewId === "string") {
            onPreviewReady(previewId);
          }
        }

        if (!TERMINAL_STATUSES.has(updated.status)) {
          timer = setTimeout(
            () => void refresh(),
            1000,
          );
        }
      } catch (err) {
        if (!active) return;

        setError(
          err instanceof Error
            ? err.message
            : "Failed to retrieve job status",
        );

        // Retry a temporary network failure.
        timer = setTimeout(
          () => void refresh(),
          2000,
        );
      } finally {
        inFlight = false;
      }
    }

    void refresh();

    return () => {
      active = false;

      if (timer !== null) {
        clearTimeout(timer);
      }
    };
  }, [jobId, onPreviewReady]);

  const currentJob =
    job?.id === jobId ? job : null;

  const status = currentJob?.status.toUpperCase() ??
    (jobId ? "LOADING" : "IDLE");

  return (
    <div className="solver-console">
      <div className="panel-heading">
        <Terminal size={16} />

        Job Monitor

        <span className="console-status">
          {status}
        </span>
      </div>

      <div className="console-output">
        {!jobId && (
          <p>
            [system] Waiting for an agent-submitted job...
          </p>
        )}

        {jobId && (
          <p>[job] ID: {jobId}</p>
        )}

        {currentJob && (
          <>
            <p>[job] Type: {currentJob.type}</p>
            <p>[status] {currentJob.status}</p>

            {currentJob.status === "completed" && (
              <p>
                [result] {JSON.stringify(currentJob.result)}
              </p>
            )}

            {currentJob.status === "failed" && (
              <p>
                [error] {currentJob.error}
              </p>
            )}
          </>
        )}

        {error && (
          <p>[error] {error}</p>
        )}
      </div>
    </div>
  );
}
