
import { useEffect, useState } from "react";
import { Terminal } from "lucide-react";

import type { Job } from "../../../services/jobs";
import { subscribeToJob } from "../../../services/jobEvents";

interface SolverConsoleProps {
  projectId: string;
  jobId: string | null;
  onPreviewReady: (artifactId: string) => void;
}

export function SolverConsole({
  projectId,
  jobId,
  onPreviewReady,
}: SolverConsoleProps) {
  const [job, setJob] = useState<Job | null>(null);
  const [connectionError, setConnectionError] =
    useState<string | null>(null);

  useEffect(() => {
    if (!jobId) return;

    setJob(null);
    setConnectionError(null);

    const unsubscribe = subscribeToJob(projectId, jobId, {
      onJob(updated) {
        setJob(updated);
        setConnectionError(null);
      },

      onEnd(completedJob) {
        setJob(completedJob);
        setConnectionError(null);

        if (completedJob.status === "completed") {
          const previewId =
            completedJob.result?.preview_artifact_id;

          if (typeof previewId === "string") {
            onPreviewReady(previewId);
          }
        }
      },

      onError(message) {
        setConnectionError(message);
      },
    });

    return unsubscribe;
  }, [projectId, jobId, onPreviewReady]);

  const currentJob =
    job?.id === jobId ? job : null;

  const status =
    currentJob?.status.toUpperCase() ??
    (jobId ? "CONNECTING" : "IDLE");

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
              <>
                <p>
                  [result]{" "}
                  {JSON.stringify(currentJob.result)}
                </p>
              </>
            )}

            {currentJob.status === "failed" && (
              <p>[error] {currentJob.error}</p>
            )}

            {currentJob.status === "cancelled" && (
              <p>[system] Job cancelled</p>
            )}
          </>
        )}

        {connectionError && (
          <p>[connection] {connectionError}</p>
        )}
      </div>
    </div>
  );
}
