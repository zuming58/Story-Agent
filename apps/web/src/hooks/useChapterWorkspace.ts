import { useEffect, useMemo } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiClientError } from "../api/client";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";
import type { ChapterContract, ChapterDraft, ChapterJob } from "../types";

const activeStatuses = new Set(["compiling_context", "drafting", "extracting", "validating", "reviewing", "revising", "cancel_requested"]);

export function useChapterWorkspace() {
  const client = useQueryClient();
  const { project, plan } = useStoryWorkspace();
  const chapterNumber = useStoryStore((state) => state.selectedChapterNumber);
  const selectedJobId = useStoryStore((state) => state.selectedChapterJobId);
  const selectChapter = useStoryStore((state) => state.selectChapter);
  const setNotice = useStoryStore((state) => state.setNotice);
  const enabled = Boolean(project);

  const contractsQuery = useQuery({ queryKey: ["chapter-contracts", project?.id], queryFn: () => api.chapterContracts(project!.id), enabled });
  const jobsQuery = useQuery({
    queryKey: ["chapter-jobs", project?.id], queryFn: () => api.chapterJobs(project!.id), enabled,
    refetchInterval: (query) => ((query.state.data as ChapterJob[] | undefined)?.some((item) => activeStatuses.has(item.status)) ? 1200 : false),
  });
  const contracts = contractsQuery.data ?? [];
  const jobs = jobsQuery.data ?? [];
  const chapterContracts = useMemo(() => contracts.filter((item) => item.chapterNumber === chapterNumber), [contracts, chapterNumber]);
  const currentContract = chapterContracts.find((item) => item.status === "locked") ?? chapterContracts.find((item) => item.status === "draft") ?? chapterContracts[0] ?? null;
  const chapterJobs = useMemo(() => jobs.filter((item) => item.contract?.chapterNumber === chapterNumber), [jobs, chapterNumber]);
  const currentJob = chapterJobs.find((item) => item.id === selectedJobId) ?? chapterJobs[0] ?? null;

  useEffect(() => {
    if (currentJob && currentJob.id !== selectedJobId) selectChapter(chapterNumber, currentJob.id);
    if (!currentJob && selectedJobId) selectChapter(chapterNumber, null);
  }, [chapterNumber, currentJob?.id, selectedJobId, selectChapter]);

  const draftsQuery = useQuery({ queryKey: ["chapter-drafts", project?.id, chapterNumber], queryFn: () => api.chapterDrafts(project!.id, chapterNumber), enabled });
  const commitsQuery = useQuery({ queryKey: ["chapter-commits", project?.id, chapterNumber], queryFn: () => api.chapterCommits(project!.id, chapterNumber), enabled });
  const drafts = (draftsQuery.data ?? []).filter((item) => !currentJob || item.chapterJobId === currentJob.id);
  const currentDraftSummary = drafts.find((item) => item.isCurrent) ?? drafts[0] ?? null;
  const draftQuery = useQuery({
    queryKey: ["chapter-draft", project?.id, currentDraftSummary?.id],
    queryFn: () => api.chapterDraft(project!.id, currentDraftSummary!.id),
    enabled: Boolean(project && currentDraftSummary),
  });
  const currentDraft = draftQuery.data ?? currentDraftSummary;
  const qualityQuery = useQuery({
    queryKey: ["chapter-quality", project?.id, currentJob?.id],
    queryFn: () => api.chapterQuality(project!.id, currentJob!.id),
    enabled: Boolean(project && currentJob && currentDraft),
  });
  const traceQuery = useQuery({
    queryKey: ["context-trace", project?.id, currentJob?.contextTraceId],
    queryFn: () => api.contextTrace(project!.id, currentJob!.contextTraceId!),
    enabled: Boolean(project && currentJob?.contextTraceId),
  });

  const invalidate = async () => {
    if (!project) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: ["chapter-contracts", project.id] }),
      client.invalidateQueries({ queryKey: ["chapter-jobs", project.id] }),
      client.invalidateQueries({ queryKey: ["chapter-drafts", project.id, chapterNumber] }),
      client.invalidateQueries({ queryKey: ["chapter-commits", project.id, chapterNumber] }),
      client.invalidateQueries({ queryKey: ["chapter-quality", project.id] }),
      client.invalidateQueries({ queryKey: ["projects"] }),
      client.invalidateQueries({ queryKey: ["audits", project.id] }),
      client.invalidateQueries({ queryKey: ["model-runs", project.id] }),
    ]);
  };

  const runAction = async <T,>(label: string, action: () => Promise<T>) => {
    try {
      const result = await action();
      await invalidate();
      setNotice(label);
      return result;
    } catch (error) {
      await invalidate();
      const message = error instanceof ApiClientError && error.payload.code === "CANON_NOT_LOCKED"
        ? "请先前往 Canon 设定库锁定故事核心，再生成章节契约。"
        : error instanceof ApiClientError && error.status === 409
          ? "数据版本已变化，已刷新最新章节状态。"
          : error instanceof Error ? error.message : "章节操作失败。";
      setNotice(message);
      throw error;
    }
  };

  const operation = useMutation({ mutationFn: async (fn: () => Promise<unknown>) => fn() });
  const invoke = <T,>(label: string, fn: () => Promise<T>) => operation.mutateAsync(() => runAction(label, fn)) as Promise<T>;

  const milestone = plan?.milestones.find((item) => chapterNumber >= item.rangeMin && chapterNumber <= item.rangeMax) ?? null;

  return {
    project, plan, chapterNumber, selectChapter, milestone,
    contracts: chapterContracts, allContracts: contracts, currentContract, jobs: chapterJobs, allJobs: jobs, currentJob,
    drafts, currentDraft, commits: commitsQuery.data ?? [], quality: qualityQuery.data ?? null, trace: traceQuery.data ?? null,
    isLoading: contractsQuery.isLoading || jobsQuery.isLoading || draftsQuery.isLoading,
    isBusy: operation.isPending || Boolean(currentJob && activeStatuses.has(currentJob.status)),
    refresh: invalidate,
    deriveContract: () => project && invoke("章节契约已生成。", () => api.deriveChapterContract(project.id, {
      chapterNumber, planNodeId: milestone?.id ?? null, title: `第${chapterNumber}章`, targetWordsMin: 2200, targetWordsMax: 3200,
    })),
    updateContract: (changes: Partial<ChapterContract>) => project && currentContract && invoke("章节契约草稿已保存。", () => api.updateChapterContract(project.id, currentContract.id, { ...changes, expectedRevision: currentContract.revision })),
    lockContract: () => project && currentContract && invoke("章节契约已锁定。", () => api.lockChapterContract(project.id, currentContract.id, currentContract.revision)),
    createJob: async () => {
      if (!project || !currentContract) return;
      const job = await invoke("章节任务已创建。", () => api.createChapterJob(project.id, currentContract.id));
      selectChapter(chapterNumber, job.id);
      return job;
    },
    runJob: (authorNote = "") => project && currentJob && invoke("章节生产已完成，等待质量复核。", () => api.runChapterJob(project.id, currentJob.id, authorNote)),
    cancelJob: () => project && currentJob && invoke("已发送停止请求。", () => api.cancelChapterJob(project.id, currentJob.id)),
    retryJob: () => project && currentJob && invoke("任务已重新排队。", () => api.retryChapterJob(project.id, currentJob.id, "从章节工作台重试")),
    reviseJob: (reason: string) => project && currentJob && invoke("自动修订已完成。", () => api.reviseChapterJob(project.id, currentJob.id, reason)),
    saveManualDraft: (contentMarkdown: string, reason: string) => project && currentJob && currentDraft && invoke("人工修改已保存为新候选版本，并重新完成质量检查。", () => api.createManualRevision(project.id, currentJob.id, {
      contentMarkdown, reason, parentDraftId: currentDraft.id, expectedParentRevision: currentDraft.revision, expectedJobRevision: currentJob.revision,
    })),
    activateDraft: (draft: ChapterDraft) => project && currentJob && invoke(`已恢复正文 v${draft.versionNumber}。`, () => api.activateChapterDraft(project.id, currentJob.id, draft.id, { expectedDraftRevision: draft.revision, expectedJobRevision: currentJob.revision })),
    acceptRisk: (findingId: string, reason: string) => project && invoke("风险接受理由已记录。", () => api.acceptQualityRisk(project.id, findingId, reason)),
    approveAndCommit: async (mode: "manual" | "guarded_auto") => {
      if (!project || !currentJob) return;
      const approved = await invoke("章节已批准。", () => api.approveChapterJob(project.id, currentJob.id, currentJob.revision, mode));
      return invoke("章节正文与故事状态已原子提交。", () => api.commitChapterJob(project.id, approved.id, approved.revision));
    },
  };
}
