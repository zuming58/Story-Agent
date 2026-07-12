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
}

export interface AgentResponse {
  message: AgentMessage;
  proposal?: ChangeProposal;
}

export type EditablePlanField = "targetChapter" | "rangeMin" | "rangeMax";

export interface ChangeOperation {
  id: string;
  field: EditablePlanField;
  label: string;
  before: number;
  after: number;
  selected: boolean;
}

export interface ImpactItem {
  id: string;
  kind: "contract" | "foreshadow" | "dependency";
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
