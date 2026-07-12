import type {
  AgentResponse,
  AgentSession,
  AgentStreamEvent,
  ApiErrorShape,
  AuditEvent,
  BackupManifest,
  ChangeProposal,
  ModelConfig,
  ModelRun,
  ModelProvider,
  ModelRoleBinding,
  PlanNode,
  ProjectCreateRequest,
  ProjectSummary,
  ProviderConnectionTest,
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
  if (response.status === 204) return undefined as T;
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
  streamMessage: async (
    sessionId: string,
    payload: { projectId: string; content: string; selectedNodeId?: string; action?: string },
    onEvent: (event: AgentStreamEvent) => void,
    signal?: AbortSignal,
  ) => {
    const response = await fetch(`/api/v1/agent/sessions/${sessionId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal,
    });
    if (!response.ok || !response.body) {
      const errorPayload = await response.json().catch(() => ({
        code: "NETWORK_ERROR", message: `请求失败（${response.status}）`, details: {}, requestId: "unknown",
      })) as ApiErrorShape;
      throw new ApiClientError(response.status, errorPayload);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() ?? "";
      for (const part of parts) {
        const dataLine = part.split("\n").find((line) => line.startsWith("data:"));
        if (!dataLine) continue;
        onEvent(JSON.parse(dataLine.slice(5).trim()) as AgentStreamEvent);
      }
    }
    if (buffer.trim()) {
      const dataLine = buffer.split("\n").find((line) => line.startsWith("data:"));
      if (dataLine) onEvent(JSON.parse(dataLine.slice(5).trim()) as AgentStreamEvent);
    }
  },
  proposals: (projectId: string) => request<ChangeProposal[]>(`/projects/${projectId}/change-proposals`),
  applyProposal: (proposalId: string, payload: { projectId: string; expectedRevision: number; selectedOperationIds: string[] }) =>
    request<ChangeProposal>(`/change-proposals/${proposalId}/apply`, { method: "POST", body: JSON.stringify(payload) }),
  rejectProposal: (proposalId: string, payload: { projectId: string; expectedRevision: number }) =>
    request<ChangeProposal>(`/change-proposals/${proposalId}/reject`, { method: "POST", body: JSON.stringify(payload) }),
  audits: (projectId: string) => request<AuditEvent[]>(`/projects/${projectId}/audit-events`),
  undo: (projectId: string, eventId: string) => request<AuditEvent>(`/projects/${projectId}/audit-events/${eventId}/undo`, { method: "POST" }),
  backup: (projectId: string) => request<BackupManifest>(`/projects/${projectId}/backups`, { method: "POST" }),
  modelRuns: (projectId: string) => request<ModelRun[]>(`/projects/${projectId}/model-runs`),
  cancelModelRun: (projectId: string, runId: string) => request<ModelRun>(`/projects/${projectId}/model-runs/${runId}/cancel`, { method: "POST" }),
  modelProviders: () => request<ModelProvider[]>("/model-providers"),
  createModelProvider: (payload: {
    name: string;
    providerType?: "openai-compatible";
    baseUrl: string;
    timeoutSeconds?: number;
    maxRetries?: number;
    isEnabled?: boolean;
    apiKey?: string;
  }) => request<ModelProvider>("/model-providers", { method: "POST", body: JSON.stringify(payload) }),
  createDeepSeekPreset: () => request<ModelProvider>("/model-providers/deepseek-preset", { method: "POST" }),
  updateModelProvider: (providerId: string, payload: Partial<{
    name: string;
    providerType: "openai-compatible";
    baseUrl: string;
    timeoutSeconds: number;
    maxRetries: number;
    isEnabled: boolean;
    apiKey: string;
    clearApiKey: boolean;
  }>) => request<ModelProvider>(`/model-providers/${providerId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteModelProvider: (providerId: string) => request<void>(`/model-providers/${providerId}`, { method: "DELETE" }),
  testModelProvider: (providerId: string) => request<ProviderConnectionTest>(`/model-providers/${providerId}/test`, { method: "POST" }),
  providerModels: (providerId: string) => request<ModelConfig[]>(`/model-providers/${providerId}/models`),
  createProviderModel: (providerId: string, payload: {
    modelId: string;
    displayName: string;
    temperature: number;
    maxOutputTokens: number;
    supportsReasoning: boolean;
    isEnabled: boolean;
  }) => request<ModelConfig>(`/model-providers/${providerId}/models`, { method: "POST", body: JSON.stringify(payload) }),
  updateModel: (modelId: string, payload: Partial<{
    modelId: string;
    displayName: string;
    temperature: number;
    maxOutputTokens: number;
    supportsReasoning: boolean;
    isEnabled: boolean;
  }>) => request<ModelConfig>(`/models/${modelId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteModel: (modelId: string) => request<void>(`/models/${modelId}`, { method: "DELETE" }),
  roleBindings: () => request<ModelRoleBinding[]>("/model-role-bindings"),
  updateRoleBinding: (role: string, payload: { modelId: string | null; dailyCostLimit?: number | null }) =>
    request<ModelRoleBinding>(`/model-role-bindings/${role}`, { method: "PUT", body: JSON.stringify(payload) }),
};
