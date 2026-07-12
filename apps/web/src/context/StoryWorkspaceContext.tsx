import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, ReactNode, useContext, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiClientError } from "../api/client";
import { useStoryStore } from "../store/useStoryStore";
import type {
  AgentMessage,
  AgentStreamEvent,
  AgentSession,
  AuditEvent,
  ChangeProposal,
  ModelRun,
  PlanNode,
  ProjectCreateRequest,
  ProjectSummary,
  StoryPlan,
} from "../types";

interface StoryWorkspaceValue {
  projects: ProjectSummary[];
  project: ProjectSummary | null;
  plan: StoryPlan | null;
  selected: PlanNode | null;
  session: AgentSession | null;
  proposal: ChangeProposal | null;
  audits: AuditEvent[];
  modelRuns: ModelRun[];
  streamPreview: string;
  runStatus: { runId: string | null; provider: string | null; model: string | null; status: "idle" | "running" | "failed" | "cancelled"; error?: string | null };
  isLoading: boolean;
  isDisconnected: boolean;
  errorMessage: string | null;
  selectProject: (id: string) => void;
  createProject: (payload: ProjectCreateRequest) => Promise<ProjectSummary>;
  updateMilestone: (id: string, changes: Partial<PlanNode>) => Promise<void>;
  sendMessage: (content: string, action?: string) => Promise<void>;
  cancelRun: () => Promise<void>;
  retryLastMessage: () => Promise<void>;
  applyProposal: (operationIds: string[]) => Promise<void>;
  rejectProposal: () => Promise<void>;
  undo: () => Promise<void>;
  createBackup: () => Promise<void>;
  retry: () => void;
}

const StoryWorkspaceContext = createContext<StoryWorkspaceValue | null>(null);

export function StoryWorkspaceProvider({ children }: { children: ReactNode }) {
  const client = useQueryClient();
  const activeProjectId = useStoryStore((state) => state.activeProjectId);
  const selectedId = useStoryStore((state) => state.selectedMilestoneId);
  const setActiveProjectId = useStoryStore((state) => state.setActiveProjectId);
  const selectMilestone = useStoryStore((state) => state.selectMilestone);
  const setNotice = useStoryStore((state) => state.setNotice);
  const [streamPreview, setStreamPreview] = useState("");
  const [runStatus, setRunStatus] = useState<StoryWorkspaceValue["runStatus"]>({ runId: null, provider: null, model: null, status: "idle", error: null });
  const lastPrompt = useRef<{ content: string; action?: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const projectsQuery = useQuery({ queryKey: ["projects"], queryFn: api.projects, retry: 1 });
  const projects = projectsQuery.data ?? [];

  useEffect(() => {
    if (projects.length && (!activeProjectId || !projects.some((item) => item.id === activeProjectId))) {
      setActiveProjectId(projects[0].id);
    }
  }, [projects, activeProjectId, setActiveProjectId]);

  const project = projects.find((item) => item.id === activeProjectId) ?? null;
  const enabled = Boolean(project?.id);
  const planQuery = useQuery({ queryKey: ["plan", project?.id], queryFn: () => api.plan(project!.id), enabled, retry: 1 });
  const sessionsQuery = useQuery({ queryKey: ["sessions", project?.id], queryFn: () => api.sessions(project!.id), enabled, retry: 1 });
  const proposalsQuery = useQuery({ queryKey: ["proposals", project?.id], queryFn: () => api.proposals(project!.id), enabled, retry: 1 });
  const auditsQuery = useQuery({ queryKey: ["audits", project?.id], queryFn: () => api.audits(project!.id), enabled, retry: 1 });
  const modelRunsQuery = useQuery({ queryKey: ["model-runs", project?.id], queryFn: () => api.modelRuns(project!.id), enabled, retry: 1 });
  const plan = planQuery.data ?? null;

  useEffect(() => {
    if (plan?.milestones.length && (!selectedId || !plan.milestones.some((item) => item.id === selectedId))) {
      selectMilestone(plan.milestones[0].id);
    }
  }, [plan, selectedId, selectMilestone]);

  const selected = plan?.milestones.find((item) => item.id === selectedId) ?? plan?.milestones[0] ?? null;
  const session = sessionsQuery.data?.[0] ?? null;
  const proposal = proposalsQuery.data?.find((item) => item.status === "pending") ?? proposalsQuery.data?.[0] ?? null;
  const audits = auditsQuery.data ?? [];
  const modelRuns = modelRunsQuery.data ?? [];

  const invalidateWorkspace = async () => {
    if (!project) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: ["plan", project.id] }),
      client.invalidateQueries({ queryKey: ["sessions", project.id] }),
      client.invalidateQueries({ queryKey: ["proposals", project.id] }),
      client.invalidateQueries({ queryKey: ["audits", project.id] }),
      client.invalidateQueries({ queryKey: ["model-runs", project.id] }),
    ]);
  };

  const createMutation = useMutation({ mutationFn: api.createProject });
  const updateMutation = useMutation({
    mutationFn: ({ id, changes }: { id: string; changes: Partial<PlanNode> }) => {
      if (!project || !plan) throw new Error("作品尚未加载");
      const node = plan.milestones.find((item) => item.id === id);
      if (!node) throw new Error("规划节点不存在");
      return api.updateNode(project.id, id, { ...changes, expectedRevision: node.revision });
    },
  });

  const handleError = (error: unknown) => {
    const message = error instanceof ApiClientError && error.status === 409
      ? "数据已被其他操作修改，已重新加载最新版本。"
      : error instanceof Error ? error.message : "操作失败。";
    setNotice(message);
  };

  const sendStreamMessage = async (content: string, action = "chat") => {
    if (!project || !selected) return;
    try {
      lastPrompt.current = { content, action };
      setStreamPreview("");
      setRunStatus({ runId: null, provider: null, model: null, status: "running", error: null });
      let activeSession = session;
      if (!activeSession) activeSession = await api.createSession(project.id, [plan?.volumeTitle ?? "当前作品"]);
      const controller = new AbortController();
      abortRef.current = controller;
      await api.streamMessage(activeSession.id, { projectId: project.id, content, selectedNodeId: selected.id, action }, (event: AgentStreamEvent) => {
        if (event.event === "run_started") setRunStatus({ runId: event.runId, provider: event.provider, model: event.model, status: "running", error: null });
        if (event.event === "text_delta") setStreamPreview((current) => current + event.delta);
        if (event.event === "completed") setRunStatus((current) => ({ ...current, runId: event.runId, status: "idle", error: null }));
        if (event.event === "failed") setRunStatus((current) => ({ ...current, runId: event.runId ?? current.runId, status: "failed", error: `${event.errorCode}: ${event.message}` }));
        if (event.event === "cancelled") setRunStatus((current) => ({ ...current, runId: event.runId, status: "cancelled", error: event.message }));
      }, controller.signal);
      abortRef.current = null;
      await invalidateWorkspace();
    } catch (error) { handleError(error); throw error; }
  };

  const value = useMemo<StoryWorkspaceValue>(() => ({
    projects,
    project,
    plan,
    selected,
    session,
    proposal,
    audits,
    modelRuns,
    streamPreview,
    runStatus,
    isLoading: projectsQuery.isLoading || (enabled && (planQuery.isLoading || sessionsQuery.isLoading)),
    isDisconnected: projectsQuery.isError,
    errorMessage: projectsQuery.error instanceof Error ? projectsQuery.error.message : null,
    selectProject: setActiveProjectId,
    createProject: async (payload) => {
      try {
        const created = await createMutation.mutateAsync(payload);
        await client.invalidateQueries({ queryKey: ["projects"] });
        setActiveProjectId(created.id);
        setNotice(`已创建作品“${created.title}”。`);
        return created;
      } catch (error) { handleError(error); throw error; }
    },
    updateMilestone: async (id, changes) => {
      try {
        await updateMutation.mutateAsync({ id, changes });
        await invalidateWorkspace();
        setNotice("规划已写入作品数据库，并记录审计事件。");
      } catch (error) { handleError(error); await invalidateWorkspace(); throw error; }
    },
    sendMessage: sendStreamMessage,
    cancelRun: async () => {
      if (!project || !runStatus.runId) {
        abortRef.current?.abort();
        return;
      }
      try {
        await api.cancelModelRun(project.id, runStatus.runId);
        abortRef.current?.abort();
        setRunStatus((current) => ({ ...current, status: "cancelled", error: "模型调用已停止。" }));
        await invalidateWorkspace();
      } catch (error) { handleError(error); throw error; }
    },
    retryLastMessage: async () => {
      const prompt = lastPrompt.current;
      if (!prompt) return;
      await sendStreamMessage(prompt.content, prompt.action);
    },
    applyProposal: async (operationIds) => {
      if (!project || !proposal) return;
      try {
        await api.applyProposal(proposal.id, { projectId: project.id, expectedRevision: proposal.revision, selectedOperationIds: operationIds });
        await invalidateWorkspace();
        setNotice("AI 修改已事务化应用，并记录审计事件。");
      } catch (error) { handleError(error); await invalidateWorkspace(); throw error; }
    },
    rejectProposal: async () => {
      if (!project || !proposal) return;
      try {
        await api.rejectProposal(proposal.id, { projectId: project.id, expectedRevision: proposal.revision });
        await invalidateWorkspace();
        setNotice("提案已拒绝，正式规划未改变。");
      } catch (error) { handleError(error); await invalidateWorkspace(); throw error; }
    },
    undo: async () => {
      if (!project) return;
      const reversible = audits.find((item) => item.payload.reversible === true);
      if (!reversible) return;
      try {
        await api.undo(project.id, reversible.id);
        await invalidateWorkspace();
        setNotice("已通过审计事件撤销上一项正式修改。");
      } catch (error) { handleError(error); await invalidateWorkspace(); throw error; }
    },
    createBackup: async () => {
      if (!project) return;
      try {
        const backup = await api.backup(project.id);
        setNotice(`备份已生成：${backup.archivePath}`);
      } catch (error) { handleError(error); throw error; }
    },
    retry: () => void projectsQuery.refetch(),
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [projects, project, plan, selected, session, proposal, audits, modelRuns, streamPreview, runStatus, projectsQuery.isLoading, projectsQuery.isError, projectsQuery.error, planQuery.isLoading, sessionsQuery.isLoading, enabled]);

  return <StoryWorkspaceContext.Provider value={value}>{children}</StoryWorkspaceContext.Provider>;
}

export function useStoryWorkspace(): StoryWorkspaceValue {
  const value = useContext(StoryWorkspaceContext);
  if (!value) throw new Error("useStoryWorkspace must be used inside StoryWorkspaceProvider");
  return value;
}
