
import { useEffect, useState } from "react";
import { Play, Terminal } from "lucide-react";

import {
  createJob,
  getJob,
  type Job,
} from "../../../services/jobs";

const DEMO_PROJECT_ID =
  "11111111-1111-4111-8111-111111111111";

const TERMINAL_STATUSES = [
  "completed",
  "failed",
  "cancelled",
];

export function SolverConsole() {
  const [job, setJob] = useState<Job | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const jobId = job?.id;
  const jobStatus = job?.status;

  useEffect(() => {
    if (!jobId || !jobStatus) return;
    if (TERMINAL_STATUSES.includes(jobStatus)) return;

    let active = true;
    let inFlight = false;

    async function refresh() {
      if (inFlight || !active) return;
      inFlight = true;

      try {
        const updated = await getJob(jobId!);

        if (active) {
          setJob(updated);
          setError(null);
        }
      } catch (err) {
        if (active) {
          setError(
            err instanceof Error
              ? err.message
              : "Failed to fetch job status"
          );
        }
      } finally {
        inFlight = false;
      }
    }

    void refresh();

    const interval = window.setInterval(
      () => void refresh(),
      1000
    );

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [jobId, jobStatus]);

  async function handleCreateGeometry() {
    setLoading(true);
    setError(null);
    setJob(null);

    try {
      const created = await createJob({
        project_id: DEMO_PROJECT_ID,
        type: "geometry.create",
        input: {
          name: "Demo Cylinder",
          definition: {
            source: "primitive",
            primitive: "cylinder",
            parameters: {
              radius: 10,
              height: 50,
            },
          },
        },
      });

      setJob(created);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Failed to create geometry job"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="solver-console">
      <div className="panel-heading">
        <Terminal size={16} />
        Job Monitor

        <span className="console-status">
          {job?.status.toUpperCase() ?? "IDLE"}
        </span>

        <button
          type="button"
          className="job-create-button"
          onClick={handleCreateGeometry}
          disabled={
            loading ||
            jobStatus === "queued" ||
            jobStatus === "running"
          }
        >
          <Play size={14} />
          {loading ? "Submitting..." : "Create Test Geometry"}
        </button>
      </div>

      <div className="console-output">
        {!job && !error && (
          <p>[system] Waiting for a simulation job...</p>
        )}

        {job && (
          <>
            <p>[job] ID: {job.id}</p>
            <p>[job] Type: {job.type}</p>
            <p>[status] {job.status}</p>

            {job.status === "completed" && (
              <p>
                [result] {JSON.stringify(job.result)}
              </p>
            )}

            {job.status === "failed" && (
              <p>[error] {job.error}</p>
            )}
          </>
        )}

        {error && <p>[error] {error}</p>}
      </div>
    </div>
  );
}
