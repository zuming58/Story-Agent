import type {
  AgentResponse,
  AgentSession,
  AgentStreamEvent,
  ApiErrorShape,
  AuditEvent,
  AutomationDailyReport,
  AutomationPolicy,
  AutomationRun,
  BackupRecord,
  BackupManifest,
  CanonChangeRequest,
  CanonGenerationProposal,
  CanonReadiness,
  CanonWorkspace,
  ChapterCommit,
  ChapterContract,
  ChapterDraft,
  ChapterJob,
  ContextPackage,
  ChangeProposal,
  ModelConfig,
  ModelRun,
  ModelProvider,
  ModelRole,
  ModelRoleBinding,
  PlanNode,
  ProjectCreateRequest,
  ProjectUpdateRequest,
  ProjectSummary,
  ProviderConnectionTest,
  QualityFinding,
  QualityReport,
  StoryPlan,
  StoryBrief,
  PlanGenerationProposal,
  TrialReadiness,
  TrialRunSize,
  MarketResearchBrief,
  ResearchJob,
  ResearchQuery,
  ResearchEvidence,
  CompetitorProfile,
  ResearchFinding,
  StoryOpportunity,
  IdeationSession,
  IdeationMessage,
  IncubationStoryBriefProposal,
  IncubationStoryBriefVersion,
  OpeningExperiment,
  OpeningCandidate,
  IncubationReadiness,
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
  updateProject: (projectId: string, payload: ProjectUpdateRequest) =>
    request<ProjectSummary>(`/projects/${projectId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  plan: (projectId: string) => request<StoryPlan>(`/projects/${projectId}/plan`),
  updateNode: (projectId: string, nodeId: string, payload: Partial<PlanNode> & { expectedRevision: number }) =>
    request<PlanNode>(`/projects/${projectId}/plan/nodes/${nodeId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  createNode: (projectId: string, payload: Omit<PlanNode, "id" | "revision">) =>
    request<PlanNode>(`/projects/${projectId}/plan/nodes`, { method: "POST", body: JSON.stringify(payload) }),
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
  audits: (projectId: string, filters?: { eventType?: string; entityType?: string; limit?: number }) => {
    const params = new URLSearchParams();
    if (filters?.eventType) params.set("eventType", filters.eventType);
    if (filters?.entityType) params.set("entityType", filters.entityType);
    if (filters?.limit) params.set("limit", String(filters.limit));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<AuditEvent[]>(`/projects/${projectId}/audit-events${suffix}`);
  },
  undo: (projectId: string, eventId: string) => request<AuditEvent>(`/projects/${projectId}/audit-events/${eventId}/undo`, { method: "POST" }),
  backup: (projectId: string) => request<BackupManifest>(`/projects/${projectId}/backups`, { method: "POST" }),
  backups: (projectId: string) => request<BackupRecord[]>(`/projects/${projectId}/backups`),
  restoreBackup: async (file: File) => {
    const form = new FormData();
    form.append("backup", file);
    const response = await fetch("/api/v1/projects/restore", { method: "POST", body: form });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({
        code: "NETWORK_ERROR", message: `请求失败（${response.status}）`, details: {}, requestId: "unknown",
      })) as ApiErrorShape;
      throw new ApiClientError(response.status, payload);
    }
    return response.json() as Promise<ProjectSummary>;
  },
  modelRuns: (projectId: string, filters?: { status?: string; role?: string; limit?: number }) => {
    const params = new URLSearchParams();
    if (filters?.status) params.set("status", filters.status);
    if (filters?.role) params.set("role", filters.role);
    if (filters?.limit) params.set("limit", String(filters.limit));
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ModelRun[]>(`/projects/${projectId}/model-runs${suffix}`);
  },
  researchBriefs: (projectId: string) => request<MarketResearchBrief[]>(`/projects/${projectId}/research/briefs`),
  saveResearchBrief: (projectId: string, payload: {
    expectedRevision: number; format: "long-form" | "short-form"; platform: string; genre: string; audience: string;
    targetChapters?: number | null; targetWords?: number | null; emotionalValue: string[]; researchDateRange?: Record<string, string>;
    includedDomains?: string[]; excludedDomains?: string[]; referenceWorks?: string[]; forbiddenContent?: string[]; commercialGoals?: string[]; notes?: string;
  }) => request<MarketResearchBrief>(`/projects/${projectId}/research/briefs`, { method: "POST", body: JSON.stringify(payload) }),
  researchJobs: (projectId: string) => request<ResearchJob[]>(`/projects/${projectId}/research/jobs`),
  createResearchJob: (projectId: string, payload: {
    briefId?: string; expectedBriefRevision: number; idempotencyKey?: string; searchProvider?: "tavily" | "deterministic";
    fetchProvider?: "firecrawl" | "deterministic"; searchApiKey?: string; fetchApiKey?: string; runImmediately?: boolean;
    limits?: { maxQueries?: number; maxPages?: number; maxCharsPerPage?: number; maxTotalChars?: number; maxCost?: number; maxRuntimeSeconds?: number; minimumSourceTypes?: number };
  }) => request<ResearchJob>(`/projects/${projectId}/research/jobs`, { method: "POST", body: JSON.stringify(payload) }),
  researchJobAction: (jobId: string, action: "run" | "resume" | "cancel" | "accept" | "reject", expectedRevision: number) =>
    request<ResearchJob>(`/research/jobs/${jobId}/${action}`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  researchQueries: (jobId: string) => request<ResearchQuery[]>(`/research/jobs/${jobId}/queries`),
  addManualResearchMaterial: (jobId: string, payload: { expectedRevision: number; perspective: string; title: string; content: string; sourceUrl?: string }) =>
    request<ResearchJob>(`/research/jobs/${jobId}/manual-materials`, { method: "POST", body: JSON.stringify(payload) }),
  analyzeManualResearchMaterials: (jobId: string, expectedRevision: number) =>
    request<ResearchJob>(`/research/jobs/${jobId}/analyze-manual-materials`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  researchEvidence: (jobId: string) => request<ResearchEvidence[]>(`/research/jobs/${jobId}/evidence`),
  researchCompetitors: (jobId: string) => request<CompetitorProfile[]>(`/research/jobs/${jobId}/competitors`),
  researchFindings: (jobId: string) => request<ResearchFinding[]>(`/research/jobs/${jobId}/findings`),
  storyOpportunities: (projectId: string, jobId?: string) => request<StoryOpportunity[]>(`/projects/${projectId}/story-opportunities${jobId ? `?jobId=${encodeURIComponent(jobId)}` : ""}`),
  createStoryOpportunities: (jobId: string, expectedJobRevision: number) => request<StoryOpportunity[]>(`/research/jobs/${jobId}/opportunities`, { method: "POST", body: JSON.stringify({ expectedJobRevision }) }),
  decideStoryOpportunity: (opportunityId: string, action: "accept" | "reject", expectedRevision: number) => request<StoryOpportunity>(`/story-opportunities/${opportunityId}/${action}`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  ideationSessions: (projectId: string) => request<IdeationSession[]>(`/projects/${projectId}/ideation/sessions`),
  createIdeationSession: (projectId: string, opportunityId: string, expectedOpportunityRevision: number) => request<IdeationSession>(`/projects/${projectId}/ideation/sessions`, { method: "POST", body: JSON.stringify({ opportunityId, expectedOpportunityRevision }) }),
  addIdeationMessage: (sessionId: string, expectedSessionRevision: number, content: string) => request<IdeationMessage>(`/ideation/sessions/${sessionId}/messages`, { method: "POST", body: JSON.stringify({ expectedSessionRevision, content }) }),
  incubationStoryBriefProposals: (projectId: string, sessionId?: string) => request<IncubationStoryBriefProposal[]>(`/projects/${projectId}/story-brief/proposals${sessionId ? `?sessionId=${encodeURIComponent(sessionId)}` : ""}`),
  createIncubationStoryBriefProposal: (sessionId: string, expectedSessionRevision: number) => request<IncubationStoryBriefProposal>(`/ideation/sessions/${sessionId}/story-brief-proposals`, { method: "POST", body: JSON.stringify({ expectedSessionRevision }) }),
  decideIncubationStoryBriefProposal: (proposalId: string, action: "apply" | "reject", expectedRevision: number) => request<IncubationStoryBriefProposal>(`/story-brief-proposals/${proposalId}/${action}`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  incubationStoryBriefVersions: (projectId: string) => request<IncubationStoryBriefVersion[]>(`/projects/${projectId}/story-brief/versions`),
  createIncubationCanonProposal: (projectId: string, expectedStoryBriefRevision: number, instructions = "") => request<CanonGenerationProposal>(`/projects/${projectId}/incubation/canon-proposals`, { method: "POST", body: JSON.stringify({ expectedStoryBriefRevision, instructions }) }),
  openingExperiments: (projectId: string) => request<OpeningExperiment[]>(`/projects/${projectId}/opening-experiments`),
  createOpeningExperiment: (projectId: string, expectedStoryBriefRevision: number, expectedCanonRevision: number) => request<OpeningExperiment>(`/projects/${projectId}/opening-experiments`, { method: "POST", body: JSON.stringify({ expectedStoryBriefRevision, expectedCanonRevision }) }),
  decideOpeningCandidate: (candidateId: string, action: "select" | "reject", expectedRevision: number, expectedExperimentRevision: number) => request<OpeningCandidate>(`/opening-candidates/${candidateId}/${action}`, { method: "POST", body: JSON.stringify({ expectedRevision, expectedExperimentRevision }) }),
  expandOpeningExperiment: (experimentId: string, selectedCandidateId: string, expectedRevision: number, expectedCandidateRevision: number) => request<OpeningExperiment>(`/opening-experiments/${experimentId}/expand-to-three-chapters`, { method: "POST", body: JSON.stringify({ expectedRevision, selectedCandidateId, expectedCandidateRevision }) }),
  approveOpeningChapter: (candidateId: string, chapterNumber: number, expectedRevision: number) => request<OpeningCandidate>(`/opening-candidates/${candidateId}/chapters/approve`, { method: "POST", body: JSON.stringify({ expectedRevision, chapterNumber }) }),
  incubationReadiness: (projectId: string) => request<IncubationReadiness>(`/projects/${projectId}/incubation-readiness`),
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
  createVolcengineCodingPlanPreset: () => request<ModelProvider>("/model-providers/volcengine-coding-plan-preset", { method: "POST" }),
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
    inputPricePerMillion?: number | null;
    outputPricePerMillion?: number | null;
  }) => request<ModelConfig>(`/model-providers/${providerId}/models`, { method: "POST", body: JSON.stringify(payload) }),
  updateModel: (modelId: string, payload: Partial<{
    modelId: string;
    displayName: string;
    temperature: number;
    maxOutputTokens: number;
    supportsReasoning: boolean;
    isEnabled: boolean;
    inputPricePerMillion: number | null;
    outputPricePerMillion: number | null;
  }>) => request<ModelConfig>(`/models/${modelId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteModel: (modelId: string) => request<void>(`/models/${modelId}`, { method: "DELETE" }),
  roleBindings: () => request<ModelRoleBinding[]>("/model-role-bindings"),
  updateRoleBinding: (role: string, payload: { modelId: string | null; dailyCostLimit?: number | null }) =>
    request<ModelRoleBinding>(`/model-role-bindings/${role}`, { method: "PUT", body: JSON.stringify(payload) }),
  updateRoleBindings: (modelIds: Partial<Record<ModelRole, string | null>>) =>
    request<ModelRoleBinding[]>("/model-role-bindings/bulk", { method: "PUT", body: JSON.stringify({ modelIds }) }),
  canon: (projectId: string) => request<CanonWorkspace>(`/projects/${projectId}/canon`),
  updateCanonDraft: (projectId: string, payload: {
    documents?: Array<Record<string, unknown>>;
    entityTypes?: Array<Record<string, unknown>>;
    entities?: Array<Record<string, unknown>>;
    relations?: Array<Record<string, unknown>>;
    rules?: Array<Record<string, unknown>>;
  }) => request<CanonWorkspace>(`/projects/${projectId}/canon/draft`, { method: "PUT", body: JSON.stringify(payload) }),
  analyzeCanon: (projectId: string, sourceText: string, title?: string) =>
    request<CanonWorkspace>(`/projects/${projectId}/canon/analyze`, { method: "POST", body: JSON.stringify({ projectId, sourceText, title }) }),
  lockCanon: (projectId: string, expectedRevision: number) =>
    request<CanonWorkspace>(`/projects/${projectId}/canon/lock`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  createCanonChangeRequest: (projectId: string, payload: {
    targetKind: CanonChangeRequest["targetKind"];
    targetId: string;
    reason: string;
    impactSummary: string;
    afterJson: Record<string, unknown>;
  }) => request<CanonChangeRequest>(`/projects/${projectId}/canon/change-requests`, { method: "POST", body: JSON.stringify({ projectId, ...payload }) }),
  applyCanonChangeRequest: (projectId: string, requestId: string, expectedRevision: number) =>
    request<CanonChangeRequest>(`/canon/change-requests/${requestId}/apply`, { method: "POST", body: JSON.stringify({ projectId, expectedRevision }) }),
  rejectCanonChangeRequest: (projectId: string, requestId: string, expectedRevision: number) =>
    request<CanonChangeRequest>(`/canon/change-requests/${requestId}/reject`, { method: "POST", body: JSON.stringify({ projectId, expectedRevision }) }),
  canonGenerationProposals: (projectId: string) =>
    request<CanonGenerationProposal[]>(`/projects/${projectId}/canon/generation-proposals`),
  createCanonGenerationProposal: (projectId: string, payload: StoryBrief) =>
    request<CanonGenerationProposal>(`/projects/${projectId}/canon/generation-proposals`, { method: "POST", body: JSON.stringify(payload) }),
  applyCanonGenerationProposal: (proposalId: string, expectedRevision: number) =>
    request<CanonWorkspace>(`/canon/generation-proposals/${proposalId}/apply`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  rejectCanonGenerationProposal: (proposalId: string, expectedRevision: number) =>
    request<CanonGenerationProposal>(`/canon/generation-proposals/${proposalId}/reject`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  canonReadiness: (projectId: string) => request<CanonReadiness>(`/projects/${projectId}/canon/readiness`),
  planGenerationProposals: (projectId: string) => request<PlanGenerationProposal[]>(`/projects/${projectId}/plan/generation-proposals`),
  createPlanGenerationProposal: (projectId: string, expectedPlanRevision: number) =>
    request<PlanGenerationProposal>(`/projects/${projectId}/plan/generation-proposals`, { method: "POST", body: JSON.stringify({ expectedPlanRevision, preciseChapterCount: 5 }) }),
  applyPlanGenerationProposal: (proposalId: string, expectedRevision: number) =>
    request<StoryPlan>(`/plan/generation-proposals/${proposalId}/apply`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  rejectPlanGenerationProposal: (proposalId: string, expectedRevision: number) =>
    request<PlanGenerationProposal>(`/plan/generation-proposals/${proposalId}/reject`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  trialReadiness: (projectId: string, chapterCount: TrialRunSize) =>
    request<TrialReadiness>(`/projects/${projectId}/trial-readiness?chapterCount=${chapterCount}`),
  automationPolicy: (projectId: string) => request<AutomationPolicy>(`/projects/${projectId}/automation/policy`),
  updateAutomationPolicy: (projectId: string, payload: Omit<AutomationPolicy, "projectId" | "nextRunAt" | "lastScheduledLocalDate" | "revision" | "createdAt" | "updatedAt"> & { expectedRevision: number }) =>
    request<AutomationPolicy>(`/projects/${projectId}/automation/policy`, { method: "PUT", body: JSON.stringify(payload) }),
  automationRuns: (projectId: string) => request<AutomationRun[]>(`/projects/${projectId}/automation/runs`),
  automationRun: (projectId: string, runId: string) => request<AutomationRun>(`/projects/${projectId}/automation/runs/${runId}`),
  createAutomationRun: (projectId: string, chapterCount: TrialRunSize, idempotencyKey: string) =>
    request<AutomationRun>(`/projects/${projectId}/automation/runs`, { method: "POST", body: JSON.stringify({ chapterCount, idempotencyKey }) }),
  cancelAutomationRun: (projectId: string, runId: string) =>
    request<AutomationRun>(`/projects/${projectId}/automation/runs/${runId}/cancel`, { method: "POST" }),
  resumeAutomationRun: (projectId: string, runId: string) =>
    request<AutomationRun>(`/projects/${projectId}/automation/runs/${runId}/resume`, { method: "POST" }),
  catchUpAutomationRun: (projectId: string, runId: string) =>
    request<AutomationRun>(`/projects/${projectId}/automation/runs/${runId}/catch-up`, { method: "POST" }),
  automationReports: (projectId: string) => request<AutomationDailyReport[]>(`/projects/${projectId}/automation/reports`),
  chapterContracts: (projectId: string) => request<ChapterContract[]>(`/projects/${projectId}/chapter-contracts`),
  deriveChapterContract: (projectId: string, payload: {
    chapterNumber: number; planNodeId?: string | null; title?: string; authorNote?: string;
    targetWordsMin?: number; targetWordsMax?: number; pov?: string;
  }) => request<ChapterContract>(`/projects/${projectId}/chapter-contracts/derive`, { method: "POST", body: JSON.stringify(payload) }),
  updateChapterContract: (projectId: string, contractId: string, payload: Partial<ChapterContract> & { expectedRevision: number }) =>
    request<ChapterContract>(`/projects/${projectId}/chapter-contracts/${contractId}`, { method: "PUT", body: JSON.stringify(payload) }),
  lockChapterContract: (projectId: string, contractId: string, expectedRevision: number) =>
    request<ChapterContract>(`/projects/${projectId}/chapter-contracts/${contractId}/lock`, { method: "POST", body: JSON.stringify({ expectedRevision }) }),
  chapterJobs: (projectId: string) => request<ChapterJob[]>(`/projects/${projectId}/chapter-jobs`),
  createChapterJob: (projectId: string, chapterContractId: string) =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs`, { method: "POST", body: JSON.stringify({ chapterContractId, idempotencyKey: `workbench:${chapterContractId}` }) }),
  runChapterJob: (projectId: string, jobId: string, authorNote = "") =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/run`, { method: "POST", body: JSON.stringify({ authorNote }) }),
  cancelChapterJob: (projectId: string, jobId: string) =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/cancel`, { method: "POST" }),
  retryChapterJob: (projectId: string, jobId: string, reason = "") =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/retry`, { method: "POST", body: JSON.stringify({ reason }) }),
  reviseChapterJob: (projectId: string, jobId: string, reason = "") =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/revise`, { method: "POST", body: JSON.stringify({ reason }) }),
  approveChapterJob: (projectId: string, jobId: string, expectedJobRevision: number, mode: "manual" | "guarded_auto") =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/approve`, { method: "POST", body: JSON.stringify({ expectedJobRevision, mode }) }),
  commitChapterJob: (projectId: string, jobId: string, expectedJobRevision: number) =>
    request<ChapterCommit>(`/projects/${projectId}/chapter-jobs/${jobId}/commit`, { method: "POST", body: JSON.stringify({ expectedJobRevision }) }),
  chapterDrafts: (projectId: string, chapterNumber: number) => request<ChapterDraft[]>(`/projects/${projectId}/chapters/${chapterNumber}/drafts`),
  chapterDraft: (projectId: string, draftId: string) => request<ChapterDraft>(`/projects/${projectId}/chapter-drafts/${draftId}`),
  createManualRevision: (projectId: string, jobId: string, payload: {
    contentMarkdown: string; reason: string; parentDraftId: string; expectedParentRevision: number; expectedJobRevision: number;
  }) => request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/manual-revisions`, { method: "POST", body: JSON.stringify(payload) }),
  activateChapterDraft: (projectId: string, jobId: string, draftId: string, payload: { expectedDraftRevision: number; expectedJobRevision: number }) =>
    request<ChapterJob>(`/projects/${projectId}/chapter-jobs/${jobId}/drafts/${draftId}/activate`, { method: "POST", body: JSON.stringify(payload) }),
  chapterQuality: (projectId: string, jobId: string) => request<QualityReport>(`/projects/${projectId}/chapter-jobs/${jobId}/quality`),
  acceptQualityRisk: (projectId: string, findingId: string, reason: string) =>
    request<QualityFinding>(`/projects/${projectId}/quality-findings/${findingId}/accept-risk`, { method: "POST", body: JSON.stringify({ reason }) }),
  chapterCommits: (projectId: string, chapterNumber: number) => request<ChapterCommit[]>(`/projects/${projectId}/chapters/${chapterNumber}/commits`),
  contextTrace: (projectId: string, traceId: string) => request<ContextPackage>(`/projects/${projectId}/context/traces/${traceId}`),
};
