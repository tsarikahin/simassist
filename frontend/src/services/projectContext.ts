
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  "http://127.0.0.1:8000";

export interface ProjectContext {
  project_id: string;
  active_geometry_job_id: string | null;
  active_geometry_artifact_id: string | null;
  updated_at: string | null;
}

export interface ProjectGeometry {
  id: string;
  project_id: string;
  type: string;
  status: string;
  created_at: string;
  input: {
    name?: string;
    definition?: {
      primitive?: string;
      source?: string;
      file_id?: string;
    };
    [key: string]: unknown;
  };
  result: {
    artifact_id?: string;
    preview_artifact_id?: string;
    [key: string]: unknown;
  } | null;
}

async function readResponse<T>(
  response: Response,
): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();

    throw new Error(
      `Project API error ${response.status}: ${detail}`,
    );
  }

  return (await response.json()) as T;
}

export async function getProjectContext(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectContext> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/context`,
    { signal },
  );

  return readResponse<ProjectContext>(response);
}

export async function getProjectGeometries(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectGeometry[]> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/geometries`,
    { signal },
  );

  return readResponse<ProjectGeometry[]>(response);
}

export async function setActiveGeometry(
  projectId: string,
  geometryJobId: string,
): Promise<ProjectContext> {
  const response = await fetch(
    `${API_BASE_URL}/api/projects/${projectId}/active-geometry`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        geometry_job_id: geometryJobId,
      }),
    },
  );

  return readResponse<ProjectContext>(response);
}

export async function renameGeometry(projectId: string, jobId: string, name: string): Promise<void> {
  await readResponse(await fetch(`${API_BASE_URL}/api/projects/${projectId}/geometries/${jobId}`, {
    method: "PATCH", headers: {"Content-Type":"application/json"}, body: JSON.stringify({name}),
  }));
}
export async function deleteGeometry(projectId: string, jobId: string): Promise<void> {
  await readResponse(await fetch(`${API_BASE_URL}/api/projects/${projectId}/geometries/${jobId}`, {method: "DELETE"}));
}
