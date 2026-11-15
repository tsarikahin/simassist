const BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export type WorkspaceProject = { id: string; name: string; created_at: string };
export type WorkspaceChat = { id: string; project_id: string; title: string; created_at: string };
export type StoredMessage = { id: number; role: "assistant" | "user"; content: string };
async function request<T>(path: string, method = "GET", body?: object): Promise<T> {
  const response = await fetch(`${BASE}/api/workspace${path}`, {
    method, headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`Workspace ${response.status}: ${await response.text()}`);
  return response.json() as Promise<T>;
}
export const listProjects = () => request<WorkspaceProject[]>("/projects");
export const createProject = (name = "Untitled Project") => request<WorkspaceProject>("/projects", "POST", {name});
export const openDefaultProject = () => request<WorkspaceProject>("/projects/default", "POST");
export const renameProject = (id: string, name: string) => request<{ok:boolean}>(`/projects/${id}`, "PATCH", {name});
export const deleteProject = (id: string) => request<{ok:boolean}>(`/projects/${id}`, "DELETE");
export const listChats = (projectId: string) => request<WorkspaceChat[]>(`/projects/${projectId}/chats`);
export const createChat = (projectId: string) => request<WorkspaceChat>(`/projects/${projectId}/chats`, "POST");
export const renameChat = (projectId: string, chatId: string, name: string) => request<{ok:boolean}>(`/projects/${projectId}/chats/${chatId}`, "PATCH", {name});
export const deleteChat = (projectId: string, chatId: string) => request<{ok:boolean}>(`/projects/${projectId}/chats/${chatId}`, "DELETE");
export const getMessages = (projectId: string, chatId: string) => request<StoredMessage[]>(`/projects/${projectId}/chats/${chatId}/messages`);

export const openLegacyProject = () => request<WorkspaceProject>("/projects/legacy", "POST");
