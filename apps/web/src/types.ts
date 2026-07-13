export type StoryMode = "long-form" | "short-form" | "short-drama";

export interface ProjectSummary {
  id: string;
  title: string;
  mode: StoryMode;
  currentChapter: number;
  totalChapters: number;
  model?: string;
  modelOnline?: boolean;
  automationSchedule?: string;
  folderPath: string;
  createdAt: string;
  updatedAt: string;
  lastOpenedAt: string;
}

export type MilestoneType = "事件" | "关键事件" | "转折点" | "高潮点";
export type PaceStatus = "smooth" | "fast" | "slow";

export interface PlanNode {
  id: string;
  title: string;
  type: MilestoneType;
  targetChapter: number;
  rangeMin: number;
  rangeMax: number;
  importance: number;
  note: string;
  prerequisites: string[];
  completionConditions: string[];
  foreshadows: string[];
  contracts: string[];
  pace: PaceStatus;
  revision: number;
}

export interface StoryMarker {
  id: string;
  kind: "hook" | "foreshadow" | "appearance" | "contract";
  chapter: number;
  label: string;
}

export interface StoryPlan {
  id: string;
  bookTitle: string;
  volumeTitle: string;
  arcTitle: string;
  chapterStart: number;
  chapterEnd: number;
  milestones: PlanNode[];
  markers: StoryMarker[];
  revision: number;
}

export type ValidationSeverity = "error" | "warning" | "info";

export interface PlanningValidation {
  id: string;
  severity: ValidationSeverity;
  rule: string;
  targetId?: string;
  message: string;
  suggestion: string;
}

export type AgentRole = "user" | "assistant";

export interface AgentMessage {
  id: string;
  role: AgentRole;
  content: string;
  timestamp: string;
}

export interface AgentSession {
  id: string;
  projectId: string;
  scope: string[];
  messages: AgentMessage[];
  status: "idle" | "thinking" | "error";
  activeRunId?: string | null;
}

export interface AgentResponse {
  message: AgentMessage;
  proposal?: ChangeProposal;
  runId?: string | null;
}

export type AgentAction = "chat" | "replan" | "logic_check" | "complete_dependencies";

export interface StreamRunStarted {
  event: "run_started";
  runId: string;
  provider: string;
  model: string;
  requestId: string;
}

export interface StreamTextDelta {
  event: "text_delta";
  runId: string;
  delta: string;
}

export interface StreamCompleted {
  event: "completed";
  runId: string;
  message: AgentMessage;
  usage?: { promptTokens?: number | null; completionTokens?: number | null; totalTokens?: number | null };
}

export interface StreamProposalStarted {
  event: "proposal_started";
  runId: string;
  provider: string;
  model: string;
  requestId: string;
}

export interface StreamProposalCompleted {
  event: "proposal_completed";
  runId: string;
  proposal: ChangeProposal;
  attempts: number;
}

export interface StreamProposalFailed {
  event: "proposal_failed";
  runId?: string | null;
  errorCode: string;
  message: string;
  attempts: number;
}

export interface StreamProposalSkipped {
  event: "proposal_skipped";
  runId: string;
  reasonCode: string;
  message: string;
  attempts: number;
}

export interface StreamFailed {
  event: "failed";
  runId?: string;
  errorCode: string;
  message: string;
  requestId?: string;
}

export interface StreamCancelled {
  event: "cancelled";
  runId: string;
  message: string;
}

export type AgentStreamEvent =
  | StreamRunStarted
  | StreamTextDelta
  | StreamCompleted
  | StreamProposalStarted
  | StreamProposalCompleted
  | StreamProposalSkipped
  | StreamProposalFailed
  | StreamFailed
  | StreamCancelled;

export type EditablePlanField = "targetChapter" | "rangeMin" | "rangeMax" | "prerequisites" | "completionConditions" | "foreshadows" | "contracts" | "note" | "pace";
export type ProposalValue = number | string | string[];

export interface ChangeOperation {
  id: string;
  field: EditablePlanField;
  label: string;
  before: ProposalValue;
  after: ProposalValue;
  selected: boolean;
}

export interface ImpactItem {
  id: string;
  kind: "contract" | "foreshadow" | "dependency" | "pace" | "chapter_window";
  label: string;
}

export interface ChangeProposal {
  id: string;
  targetId: string;
  targetTitle: string;
  reason: string;
  operations: ChangeOperation[];
  impacts: ImpactItem[];
  status: "pending" | "accepted" | "rejected";
  revision: number;
}

export interface AuditEvent {
  id: string;
  eventType: string;
  entityType: string;
  entityId: string;
  payload: Record<string, unknown>;
  requestId: string;
  createdAt: string;
}

export interface BackupManifest {
  backupId: string;
  projectId: string;
  projectTitle: string;
  createdAt: string;
  files: Record<string, string>;
  archivePath: string;
}

export interface BackupRecord extends BackupManifest {
  sizeBytes: number;
  isValid: boolean;
}

export interface ModelProvider {
  id: string;
  name: string;
  providerType: "openai-compatible";
  baseUrl: string;
  timeoutSeconds: number;
  maxRetries: number;
  isEnabled: boolean;
  hasApiKey: boolean;
  apiKeyPreview?: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface ModelConfig {
  id: string;
  providerId: string;
  providerName: string;
  modelId: string;
  displayName: string;
  temperature: number;
  maxOutputTokens: number;
  supportsReasoning: boolean;
  isEnabled: boolean;
  createdAt: string;
  updatedAt: string;
}

export type ModelRole =
  | "architect"
  | "planner"
  | "chinese_writer"
  | "fact_extractor"
  | "logic_reviewer"
  | "continuity_reviewer"
  | "story_editor"
  | "style_reviewer"
  | "reviser"
  | "embedding";

export interface ModelRoleBinding {
  role: ModelRole;
  modelId: string | null;
  model: ModelConfig | null;
  dailyCostLimit: number | null;
  updatedAt: string;
}

export interface ModelRun {
  id: string;
  sessionId: string | null;
  role: string;
  providerId: string | null;
  providerName: string;
  modelConfigId: string | null;
  modelId: string;
  status: string;
  promptTokens: number | null;
  completionTokens: number | null;
  totalTokens: number | null;
  durationMs: number | null;
  errorCode: string | null;
  diagnostic?: Record<string, unknown> | null;
  requestId: string;
  retryCount: number;
  startedAt: string;
  endedAt: string | null;
}

export interface ProviderConnectionTest {
  ok: boolean;
  status: "success" | "missing_api_key" | "auth_failed" | "timeout" | "network_error" | "invalid_response" | "credential_unavailable";
  providerId: string;
  providerName: string;
  model?: string | null;
  message: string;
}

export interface ApiErrorShape {
  code: string;
  message: string;
  details: Record<string, unknown>;
  requestId: string;
}

export interface ProjectCreateRequest {
  title: string;
  mode: StoryMode;
  totalChapters: number;
}

export interface ChapterContract {
  id: string;
  projectId: string;
  chapterNumber: number;
  title: string;
  planNodeId: string | null;
  planNodeRevision: number;
  canonRevisionDigest: string;
  stateSnapshotId: string | null;
  objective: Record<string, unknown>;
  allowedScope: Record<string, unknown>;
  forbiddenScope: Record<string, unknown>;
  requiredCharacters: string[];
  requiredForeshadows: string[];
  requiredHooks: string[];
  completionConditions: string[];
  pov: string;
  targetWordsMin: number;
  targetWordsMax: number;
  pace: string;
  status: "draft" | "locked" | "superseded";
  revision: number;
  createdAt: string;
  updatedAt: string;
  lockedAt: string | null;
}

export type ChapterJobStatus =
  | "queued" | "compiling_context" | "drafting" | "extracting" | "validating"
  | "reviewing" | "revising" | "human_review" | "approved" | "completed"
  | "failed" | "cancel_requested" | "cancelled" | "interrupted";

export interface ChapterJob {
  id: string;
  projectId: string;
  chapterContractId: string;
  status: ChapterJobStatus;
  attemptNumber: number;
  currentRevisionRound: number;
  contextTraceId: string | null;
  idempotencyKey: string;
  errorCode: string | null;
  diagnostic: Record<string, unknown> | null;
  revision: number;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
  updatedAt: string;
  contract: ChapterContract | null;
}

export interface ChapterExtraction {
  id: string;
  projectId: string;
  chapterDraftId: string;
  modelRunId: string | null;
  payload: Record<string, unknown>;
  schemaVersion: number;
  status: string;
  validationErrors: Array<Record<string, unknown>>;
  checksum: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChapterDraft {
  id: string;
  projectId: string;
  chapterJobId: string;
  chapterContractId: string;
  versionNumber: number;
  parentDraftId: string | null;
  kind: string;
  contentMarkdown: string;
  wordCount: number;
  checksum: string;
  modelRunId: string | null;
  contextTraceId: string | null;
  status: string;
  isCurrent: boolean;
  revision: number;
  createdAt: string;
  updatedAt: string;
  extraction?: ChapterExtraction;
}

export interface QualityFinding {
  id: string;
  projectId: string;
  qualityRunId: string;
  chapterDraftId: string;
  ruleCode: string;
  severity: "info" | "warning" | "error" | "blocker";
  category: string;
  message: string;
  evidence: unknown[];
  location: Record<string, unknown>;
  suggestedFix: string;
  fingerprint: string;
  status: "open" | "fixed" | "accepted_risk" | "superseded";
  acceptedReason: string | null;
  createdAt: string;
  updatedAt: string;
}

export interface QualityRun {
  id: string;
  projectId: string;
  chapterJobId: string;
  chapterDraftId: string;
  gateType: "deterministic" | "model";
  reviewerRole: string | null;
  modelRunId: string | null;
  status: string;
  summary: Record<string, unknown>;
  createdAt: string;
  completedAt: string | null;
  findings: QualityFinding[];
}

export interface QualityReport {
  jobId: string;
  currentDraftId: string | null;
  openBlockingCount: number;
  runs: QualityRun[];
  findings: QualityFinding[];
}

export interface ChapterCommit {
  id: string;
  projectId: string;
  chapterNumber: number;
  chapterContractId: string;
  approvedDraftId: string;
  sourceVersionId: string;
  stateSnapshotId: string | null;
  qualitySummary: Record<string, unknown>;
  checksum: string;
  status: string;
  isCurrent: boolean;
  revision: number;
  committedAt: string;
  createdAt: string;
}

export interface ContextTraceItem {
  id: string;
  kind: string;
  sourceId: string;
  sourceVersionId: string | null;
  title: string;
  reason: string;
  tokenEstimate: number;
  payload: Record<string, unknown>;
}

export interface ContextPackage {
  traceId: string;
  projectId: string;
  role: string;
  query: string;
  selectedNodeId: string | null;
  tokenBudget: number;
  items: ContextTraceItem[];
  payload: Record<string, unknown>;
  checksum: string;
}
