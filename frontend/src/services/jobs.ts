
export type JobStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type JobType =
  | "geometry.create"
  | "mesh.generate"
  | "simulation.run";

export interface Job {
  id: string;
  project_id: string;
  type: JobType;
  status: JobStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  input: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface JobCreateRequest {
  project_id: string;
  type: JobType;
  input: Record<string, unknown>;
}

const API_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const details = await response.text();
    throw new Error(
      `API error ${response.status}: ${details}`
    );
  }

  return (await response.json()) as T;
}

export function createJob(
  payload: JobCreateRequest
): Promise<Job> {
  return request<Job>("/api/jobs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/api/jobs/${jobId}`);
}

export function listProjectJobs(
  projectId: string
): Promise<Job[]> {
  return request<Job[]>(
    `/api/projects/${projectId}/jobs`
  );
}
