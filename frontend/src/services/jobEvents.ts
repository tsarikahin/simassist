
import type { Job } from "./jobs";

const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface JobEventHandlers {
  onJob: (job: Job) => void;
  onEnd?: (job: Job) => void;
  onError?: (message: string) => void;
}

export function subscribeToJob(
  projectId: string,
  jobId: string,
  handlers: JobEventHandlers,
): () => void {
  const url =
    `${API_URL}/api/projects/${encodeURIComponent(projectId)}` +
    `/jobs/${encodeURIComponent(jobId)}/events`;

  const source = new EventSource(url);
  let closed = false;

  source.addEventListener("job", (event: MessageEvent) => {
    if (closed) return;

    try {
      const job = JSON.parse(event.data) as Job;

      if (job.id !== jobId || job.project_id !== projectId) {
        throw new Error("Unexpected job event");
      }

      handlers.onJob(job);
    } catch {
      handlers.onError?.("Invalid job event received");
      closed = true;
      source.close();
    }
  });

  source.addEventListener("end", (event: MessageEvent) => {
    if (closed) return;

    try {
      const job = JSON.parse(event.data) as Job;

      if (job.id !== jobId || job.project_id !== projectId) {
        throw new Error("Unexpected job completion event");
      }

      handlers.onEnd?.(job);
    } catch {
      handlers.onError?.("Invalid job completion event");
    } finally {
      closed = true;
      source.close();
    }
  });

  source.onerror = () => {
    if (!closed) {
      handlers.onError?.(
        "Job event connection interrupted; reconnecting...",
      );
    }
  };

  return () => {
    closed = true;
    source.close();
  };
}
