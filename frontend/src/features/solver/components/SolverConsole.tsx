
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Clock3,
  LoaderCircle,
  Terminal,
} from "lucide-react";

import type { Job } from "../../../services/jobs";
import { subscribeToJob } from "../../../services/jobEvents";

interface SolverConsoleProps {
  projectId: string;
  jobIds: string[];
  onPreviewReady: (artifactId: string) => void;
}

type DisplayStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "connecting";

function getJobTitle(type: string): string {
  switch (type) {
    case "geometry.create":
      return "Geometry Creation";
    case "mesh.generate":
      return "3D Mesh Generation";
    case "simulation.run":
      return "Simulation";
    default:
      return type;
  }
}

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function StatusIcon({
  status,
}: {
  status: DisplayStatus;
}) {
  switch (status) {
    case "completed":
      return <CheckCircle2 size={17} color="#34d399" />;

    case "failed":
    case "cancelled":
      return <AlertCircle size={17} color="#fb7185" />;

    case "running":
      return (
        <LoaderCircle
          size={17}
          className="workflow-spinner"
          color="#60a5fa"
        />
      );

    case "queued":
      return <Clock3 size={17} color="#fbbf24" />;

    default:
      return <Circle size={17} color="#94a3b8" />;
  }
}

function formatJobResult(job: Job): string | null {
  if (job.status !== "completed" || !job.result) {
    return null;
  }

  if (job.type === "geometry.create") {
    return "STEP geometry and preview generated";
  }

  if (job.type === "mesh.generate") {
    const metadata = job.result.metadata;

    if (isRecord(metadata)) {
      const nodeCount = metadata["node_count"];
      const elementCount = metadata["element_count"];

      if (
        typeof nodeCount === "number" &&
        typeof elementCount === "number"
      ) {
        return (
          `${nodeCount.toLocaleString()} nodes · ` +
          `${elementCount.toLocaleString()} elements`
        );
      }
    }

    return "Mesh artifact generated";
  }

  return "Job completed";
}

export function SolverConsole({
  projectId,
  jobIds,
  onPreviewReady,
}: SolverConsoleProps) {
  const [jobsById, setJobsById] = useState<
    Record<string, Job>
  >({});

  const [errorsById, setErrorsById] = useState<
    Record<string, string>
  >({});

  const lastPreviewIdRef = useRef<string | null>(null);

  const handleJobUpdate = useCallback(
    (updated: Job) => {
      setJobsById((previous) => ({
        ...previous,
        [updated.id]: updated,
      }));

      setErrorsById((previous) => {
        if (!previous[updated.id]) {
          return previous;
        }

        const next = { ...previous };
        delete next[updated.id];
        return next;
      });

      if (
        updated.type === "geometry.create" &&
        updated.status === "completed"
      ) {
        const previewId =
          updated.result?.preview_artifact_id;

        if (
          typeof previewId === "string" &&
          previewId !== lastPreviewIdRef.current
        ) {
          lastPreviewIdRef.current = previewId;
          onPreviewReady(previewId);
        }
      }
    },
    [onPreviewReady],
  );

  useEffect(() => {
    if (jobIds.length === 0) {
      return;
    }

    const unsubscribers = jobIds.map((jobId) =>
      subscribeToJob(projectId, jobId, {
        onJob: handleJobUpdate,
        onEnd: handleJobUpdate,

        onError(message) {
          setErrorsById((previous) => ({
            ...previous,
            [jobId]: message,
          }));
        },
      }),
    );

    return () => {
      unsubscribers.forEach((unsubscribe) => {
        unsubscribe();
      });
    };
  }, [projectId, jobIds, handleJobUpdate]);

  const activeJobs = jobIds.map(
    (id) => jobsById[id] ?? null,
  );

  const allCompleted =
    jobIds.length > 0 &&
    activeJobs.every(
      (job) => job?.status === "completed",
    );

  const hasFailed = activeJobs.some(
    (job) =>
      job?.status === "failed" ||
      job?.status === "cancelled",
  );

  const hasRunning = activeJobs.some(
    (job) => job?.status === "running",
  );

  const overallStatus =
    jobIds.length === 0
      ? "IDLE"
      : hasFailed
        ? "FAILED"
        : allCompleted
          ? "COMPLETED"
          : hasRunning
            ? "RUNNING"
            : "PENDING";

  return (
    <div className="solver-console">
      <div className="panel-heading">
        <Terminal size={16} />
        <span>Workflow Monitor</span>

        <span className="console-status">
          {overallStatus}
        </span>
      </div>

      <div className="console-output workflow-console">
        {jobIds.length === 0 && (
          <p>
            [system] Waiting for an agent-submitted workflow...
          </p>
        )}

        {jobIds.map((jobId, index) => {
          const job = jobsById[jobId] ?? null;

          const status: DisplayStatus =
            job?.status === "queued" ||
            job?.status === "running" ||
            job?.status === "completed" ||
            job?.status === "failed" ||
            job?.status === "cancelled"
              ? job.status
              : "connecting";

          const summary = job
            ? formatJobResult(job)
            : null;

          return (
            <div
              key={jobId}
              className="workflow-step"
            >
              <div className="workflow-step-header">
                <StatusIcon status={status} />

                <span className="workflow-step-index">
                  {index + 1}.
                </span>

                <strong>
                  {job
                    ? getJobTitle(job.type)
                    : "Loading job..."}
                </strong>

                <span
                  className={
                    "workflow-status " +
                    `workflow-status-${status}`
                  }
                >
                  {status.toUpperCase()}
                </span>
              </div>

              <div className="workflow-step-body">
                <div className="workflow-job-id">
                  Job: {jobId}
                </div>

                {job?.depends_on && (
                  <div className="workflow-dependency">
                    Depends on: {job.depends_on}
                  </div>
                )}

                {summary && (
                  <div className="workflow-result">
                    {summary}
                  </div>
                )}

                {job?.status === "failed" && (
                  <div className="workflow-error">
                    {job.error ?? "Job failed"}
                  </div>
                )}

                {job?.status === "cancelled" && (
                  <div className="workflow-error">
                    Job cancelled
                  </div>
                )}

                {errorsById[jobId] && (
                  <div className="workflow-connection-error">
                    {errorsById[jobId]}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
