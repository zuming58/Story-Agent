import type {
  AgentResponse,
  AgentSession,
  ApiErrorShape,
  AuditEvent,
  BackupManifest,
  ChangeProposal,
  PlanNode,
  ProjectCreateRequest,
  ProjectSummary,
  StoryPlan,
} from "../types";

export class ApiClientError extends Error {
  constructor(public status: number, public payload: ApiErrorShape) {
    super(payload.message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({
      code: "NETWORK_ERROR", message: `请求失败（${response.status}）`, details: {}, requestId: "unknown",
    })) as ApiErrorShape;
    throw new ApiClientError(response.status, payload);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<{ status: string; storage: string }>("/health"),
  projects: () => request<ProjectSummary[]>("/projects"),
  createProject: (payload: ProjectCreateRequest) => request<ProjectSummary>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  plan: (projectId: string) => request<StoryPlan>(`/projects/${projectId}/plan`),
  updateNode: (projectId: string, nodeId: string, payload: Partial<PlanNode> & { expectedRevision: number }) =>
    request<PlanNode>(`/projects/${projectId}/plan/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  sessions: (projectId: string) => request<AgentSession[]>(`/projects/${projectId}/agent/sessions`),
  createSession: (projectId: string, scope: string[]) => request<AgentSession>(`/projects/${projectId}/agent/sessions`, { method: "POST", body: JSON.stringify({ scope }) }),
  sendMessage: (sessionId: string, payload: { projectId: string; content: string; selectedNodeId?: string }) =>
    request<AgentResponse>(`/agent/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify(payload) }),
  proposals: (projectId: string) => request<ChangeProposal[]>(`/projects/${projectId}/change-proposals`),
  applyProposal: (proposalId: string, payload: { projectId: string; expectedRevision: number; selectedOperationIds: string[] }) =>
    request<ChangeProposal>(`/change-proposals/${proposalId}/apply`, { method: "POST", body: JSON.stringify(payload) }),
  rejectProposal: (proposalId: string, payload: { projectId: string; expectedRevision: number }) =>
    request<ChangeProposal>(`/change-proposals/${proposalId}/reject`, { method: "POST", body: JSON.stringify(payload) }),
  audits: (projectId: string) => request<AuditEvent[]>(`/projects/${projectId}/audit-events`),
  undo: (projectId: string, eventId: string) => request<AuditEvent>(`/projects/${projectId}/audit-events/${eventId}/undo`, { method: "POST" }),
  backup: (projectId: string) => request<BackupManifest>(`/projects/${projectId}/backups`, { method: "POST" }),
};
