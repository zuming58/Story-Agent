import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight, Books, Brain, Check, CheckCircle, CircleNotch, Compass, Flask,
  Lightbulb, LockKey, MagnifyingGlass, PaperPlaneTilt, ShieldCheck, Sparkle, WarningCircle, X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiClientError } from "../api/client";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";

const stages = [
  ["研究目标", "先说清楚写给谁看"], ["市场调研", "证据不是模型印象"], ["故事机会", "比较三到五个方向"],
  ["人机共创", "讨论到你真正认可"], ["StoryBrief", "冻结创作承诺"], ["Canon 与开篇", "三种开头先试后定"],
] as const;

const readinessLabels: Record<string, string> = {
  INCUBATION_MODEL_ROLE_MISSING: "模型角色未配置",
  INCUBATION_MODEL_UNAVAILABLE: "模型或密钥不可用",
  INCUBATION_PROVIDER_NOT_TESTED: "Provider 尚未测试",
  INCUBATION_MODELS_READY: "孵化模型已就绪",
  STORY_BRIEF_ACCEPTED: "StoryBrief 尚未确认",
  CANON_DRAFT: "Canon 草稿尚未建立",
  OPENING_SELECTED: "开篇方向尚未选择",
  STYLE_BASELINE: "文风基线尚未建立",
  FIRST_THREE_MANUAL_ONLY: "前三章需人工批准",
};

const readinessStageLabels: Record<string, string> = {
  research_brief: "等待填写研究目标",
  incubating: "正在完成创意孵化",
  ready_for_manual_handoff: "可以进入人工确认",
};

const researchErrorMessages: Record<string, string> = {
  RESEARCH_QUERY_PLAN_INVALID: "研究模型没有按要求返回查询列表。系统已增加结构修复，更新后请点击“恢复任务”重试。",
  RESEARCH_QUERY_PLAN_INCOMPLETE: "研究模型返回的六类查询不完整。系统会先尝试结构修复，仍不完整时才停止。",
  SEARCH_API_KEY_MISSING: "Tavily 密钥尚未配置，请更新凭据后恢复任务。",
  FETCH_API_KEY_MISSING: "Firecrawl 密钥尚未配置，请更新凭据后恢复任务。",
  STARTUP_RECOVERY: "服务重启时分析被中断；报告材料已保留，可点击“重新分析已导入报告”。",
};

const researchStages: Record<string, string> = { planning: "规划查询", searching: "搜索公开网页", fetching: "提取网页", analyzing: "抽取证据与分析", awaiting_review: "等待人工确认", accepted: "研究已接受", insufficient_evidence: "证据不足", failed: "任务失败", cancelled: "已取消" };
const perspectiveLabels: Record<string, string> = { integrated_report: "外部综合报告", platform_trends: "平台趋势", genre_leaders: "同题材作品", reader_praise: "读者喜欢", reader_dropoff: "读者弃书", opening_strategy: "开篇策略", serial_engine: "连载机制" };
const researchFailureHelp: Record<string, string> = { SEARCH_AUTH_FAILED: "Tavily 拒绝了当前密钥，请更新 Tavily API Key 后恢复任务。", SEARCH_RATE_LIMITED: "Tavily 当前限流，请稍后恢复任务，无需重输密钥。", SEARCH_PROVIDER_FAILED: "Tavily 搜索没有得到可用响应；请查看下方运行轨迹中的具体查询。" };

function lines(value: string) { return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean); }
function createBriefForm(targetChapters = "") {
  return {
    format: "long-form" as "long-form" | "short-form", platform: "番茄小说", genre: "",
    audience: "喜欢强钩子、具体人物欲望和持续悬念的成年读者", targetChapters,
    emotionalValue: "紧张\n好奇\n情绪释放", includedDomains: "", excludedDomains: "",
    referenceWorks: "", forbiddenContent: "不模仿具体作者原文\n不以堆设定代替剧情", commercialGoals: "前三章留存\n稳定追读",
    notes: "先研究读者为什么继续读、为什么弃书，再讨论故事。",
  };
}
function errorText(error: unknown) {
  if (error instanceof ApiClientError) return `${error.payload.code}：${error.payload.message}`;
  return error instanceof Error ? error.message : "操作失败";
}
function jsonPreview(value: unknown) { return JSON.stringify(value ?? {}, null, 2); }

export function StoryIncubatorPage() {
  const { project } = useStoryWorkspace();
  const navigate = useNavigate();
  const client = useQueryClient();
  const setNotice = useStoryStore((state) => state.setNotice);
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [researchKeys, setResearchKeys] = useState({ tavily: "", firecrawl: "" });
  const [manualMaterial, setManualMaterial] = useState({ title: "", sourceUrl: "", content: "" });
  const [reportImporting, setReportImporting] = useState(false);
  const [message, setMessage] = useState("");
  const [briefForm, setBriefForm] = useState(() => createBriefForm());
  const initializedDraftProjectId = useRef<string | null>(null);

  const enabled = Boolean(project);
  const briefsQuery = useQuery({ queryKey: ["incubator-briefs", project?.id], queryFn: () => api.researchBriefs(project!.id), enabled });
  const jobsQuery = useQuery({ queryKey: ["incubator-jobs", project?.id], queryFn: () => api.researchJobs(project!.id), enabled, refetchInterval: 8000 });
  const opportunitiesQuery = useQuery({ queryKey: ["incubator-opportunities", project?.id], queryFn: () => api.storyOpportunities(project!.id), enabled });
  const sessionsQuery = useQuery({ queryKey: ["incubator-sessions", project?.id], queryFn: () => api.ideationSessions(project!.id), enabled });
  const proposalsQuery = useQuery({ queryKey: ["incubator-brief-proposals", project?.id], queryFn: () => api.incubationStoryBriefProposals(project!.id), enabled });
  const versionsQuery = useQuery({ queryKey: ["incubator-brief-versions", project?.id], queryFn: () => api.incubationStoryBriefVersions(project!.id), enabled });
  const canonQuery = useQuery({ queryKey: ["canon", project?.id], queryFn: () => api.canon(project!.id), enabled });
  const canonProposalsQuery = useQuery({ queryKey: ["canon-generation-proposals", project?.id], queryFn: () => api.canonGenerationProposals(project!.id), enabled });
  const experimentsQuery = useQuery({ queryKey: ["incubator-openings", project?.id], queryFn: () => api.openingExperiments(project!.id), enabled });
  const readinessQuery = useQuery({ queryKey: ["incubator-readiness", project?.id], queryFn: () => api.incubationReadiness(project!.id), enabled });

  const currentBrief = briefsQuery.data?.find((item) => item.status === "current") ?? null;
  const currentJob = jobsQuery.data?.find((item) => item.briefId === currentBrief?.id) ?? jobsQuery.data?.[0] ?? null;
  const acceptedOpportunity = opportunitiesQuery.data?.find((item) => item.status === "accepted" && item.isCurrent) ?? null;
  const activeSession = sessionsQuery.data?.find((item) => item.opportunityId === acceptedOpportunity?.id) ?? sessionsQuery.data?.[0] ?? null;
  const pendingBriefProposal = proposalsQuery.data?.find((item) => item.status === "pending") ?? null;
  const currentStoryBrief = versionsQuery.data?.find((item) => item.isCurrent) ?? null;
  const incubationCanonProposals = canonProposalsQuery.data?.filter((item) => (item.brief as unknown as { incubation?: boolean })?.incubation) ?? [];
  const latestCanonProposal = incubationCanonProposals[0] ?? null;
  const latestExperiment = experimentsQuery.data?.[0] ?? null;
  const currentCanon = canonQuery.data?.documents.find((item) => item.id === "story-core") ?? canonQuery.data?.documents[0] ?? null;
  const researchNeedsRecovery = Boolean(currentJob && ["failed", "cancelled", "insufficient_evidence"].includes(currentJob.status));
  const ideationUserTurns = activeSession?.messages.filter((item) => item.role === "user").length ?? 0;

  const evidenceQuery = useQuery({ queryKey: ["incubator-evidence", currentJob?.id], queryFn: () => api.researchEvidence(currentJob!.id), enabled: Boolean(currentJob) });
  const competitorsQuery = useQuery({ queryKey: ["incubator-competitors", currentJob?.id], queryFn: () => api.researchCompetitors(currentJob!.id), enabled: Boolean(currentJob) });
  const findingsQuery = useQuery({ queryKey: ["incubator-findings", currentJob?.id], queryFn: () => api.researchFindings(currentJob!.id), enabled: Boolean(currentJob) });
  const researchQueriesQuery = useQuery({
    queryKey: ["incubator-research-queries", currentJob?.id], queryFn: () => api.researchQueries(currentJob!.id), enabled: Boolean(currentJob),
    refetchInterval: currentJob && ["planning", "searching", "fetching", "analyzing"].includes(currentJob.status) ? 2500 : false,
  });

  const completed = useMemo(() => [
    Boolean(currentBrief), currentJob?.status === "accepted", Boolean(acceptedOpportunity), Boolean(activeSession?.messages.length),
    Boolean(currentStoryBrief), Boolean(readinessQuery.data?.ready),
  ], [currentBrief, currentJob?.status, acceptedOpportunity, activeSession?.messages.length, currentStoryBrief, readinessQuery.data?.ready]);

  useEffect(() => {
    if (!project || !briefsQuery.isSuccess) return;
    if (currentBrief) {
      initializedDraftProjectId.current = project.id;
      setBriefForm({
        format: currentBrief.format,
        platform: currentBrief.platform,
        genre: currentBrief.genre,
        audience: currentBrief.audience,
        targetChapters: String(currentBrief.format === "long-form" ? (currentBrief.targetChapters ?? "") : (currentBrief.targetWords ?? "")),
        emotionalValue: currentBrief.emotionalValue.join("\n"),
        includedDomains: currentBrief.includedDomains.join("\n"),
        excludedDomains: currentBrief.excludedDomains.join("\n"),
        referenceWorks: currentBrief.referenceWorks.join("\n"),
        forbiddenContent: currentBrief.forbiddenContent.join("\n"),
        commercialGoals: currentBrief.commercialGoals.join("\n"),
        notes: currentBrief.notes,
      });
      return;
    }
    if (initializedDraftProjectId.current === project.id) return;
    initializedDraftProjectId.current = project.id;
    const isShortForm = project.mode === "short-form";
    setBriefForm({
      ...createBriefForm(isShortForm ? "8000" : String(project.totalChapters)),
      format: isShortForm ? "short-form" : "long-form",
    });
  }, [briefsQuery.isSuccess, currentBrief, project]);

  const savedChapterMismatch = Boolean(
    project && currentBrief?.format === "long-form" && currentBrief.targetChapters !== project.totalChapters,
  );
  const formMatchesProjectChapters = Boolean(project && Number(briefForm.targetChapters) === project.totalChapters);
  const targetAmount = Number(briefForm.targetChapters);
  const targetAmountValid = Number.isInteger(targetAmount) && (
    briefForm.format === "long-form" ? targetAmount >= 1 && targetAmount <= 5000 : targetAmount >= 1000 && targetAmount <= 20_000_000
  );

  useEffect(() => {
    setAgentContext(["创意孵化", stages[stage][0], project?.title ?? "当前作品"]);
    return () => setAgentContext([]);
  }, [project?.title, setAgentContext, stage]);

  const refresh = async () => {
    if (!project) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: ["incubator-briefs", project.id] }), client.invalidateQueries({ queryKey: ["incubator-jobs", project.id] }),
      client.invalidateQueries({ queryKey: ["incubator-opportunities", project.id] }), client.invalidateQueries({ queryKey: ["incubator-sessions", project.id] }),
      client.invalidateQueries({ queryKey: ["incubator-brief-proposals", project.id] }), client.invalidateQueries({ queryKey: ["incubator-brief-versions", project.id] }),
      client.invalidateQueries({ queryKey: ["canon", project.id] }), client.invalidateQueries({ queryKey: ["canon-generation-proposals", project.id] }),
      client.invalidateQueries({ queryKey: ["incubator-openings", project.id] }), client.invalidateQueries({ queryKey: ["incubator-readiness", project.id] }),
      client.invalidateQueries({ queryKey: ["incubator-research-queries"] }), client.invalidateQueries({ queryKey: ["incubator-evidence"] }),
      client.invalidateQueries({ queryKey: ["incubator-competitors"] }), client.invalidateQueries({ queryKey: ["incubator-findings"] }),
    ]);
  };
  const mutation = useMutation({ mutationFn: async ({ action }: { action: () => Promise<unknown> }) => action(), onSuccess: async () => { setError(null); await refresh(); }, onError: (cause) => setError(errorText(cause)) });
  const run = async (label: string, action: () => Promise<unknown>) => { await mutation.mutateAsync({ action }); setNotice(label); };

  const saveBrief = () => {
    if (!project) return;
    void run("研究目标已保存", () => api.saveResearchBrief(project.id, {
      expectedRevision: currentBrief?.revision ?? 0, format: briefForm.format, platform: briefForm.platform,
      genre: briefForm.genre, audience: briefForm.audience, targetChapters: briefForm.format === "long-form" ? Number(briefForm.targetChapters) : null,
      targetWords: briefForm.format === "short-form" ? Math.max(1000, Number(briefForm.targetChapters) || 8000) : null,
      emotionalValue: lines(briefForm.emotionalValue), includedDomains: lines(briefForm.includedDomains), excludedDomains: lines(briefForm.excludedDomains),
      referenceWorks: lines(briefForm.referenceWorks), forbiddenContent: lines(briefForm.forbiddenContent), commercialGoals: lines(briefForm.commercialGoals), notes: briefForm.notes,
    })).then(() => setStage(1));
  };
  const startResearch = () => {
    if (!project || !currentBrief) return;
    void run(currentJob ? "研究凭据已安全更新，请点击恢复任务" : "市场调研已启动", () => api.createResearchJob(project.id, {
      briefId: currentBrief.id, expectedBriefRevision: currentBrief.revision, idempotencyKey: `research:${currentBrief.checksum}`,
      searchProvider: "tavily", fetchProvider: "firecrawl", searchApiKey: researchKeys.tavily || undefined, fetchApiKey: researchKeys.firecrawl || undefined,
      runImmediately: true, limits: { maxQueries: 6, maxPages: 24, maxTotalChars: 160000, maxCost: 8, maxRuntimeSeconds: 900, minimumSourceTypes: 3 },
    }));
  };
  const actOnJob = (action: "run" | "resume" | "cancel" | "accept" | "reject") => currentJob && void run(`研究任务已${action === "accept" ? "接受" : action === "reject" ? "拒绝" : "更新"}`, () => api.researchJobAction(currentJob.id, action, currentJob.revision));
  const importAndAnalyzeResearchReport = () => currentJob && void (async () => {
    setReportImporting(true);
    setError(null);
    try {
      const saved = await api.addManualResearchMaterial(currentJob.id, {
        expectedRevision: currentJob.revision, title: manualMaterial.title.trim() || "外部综合调研报告", content: manualMaterial.content.trim(), sourceUrl: manualMaterial.sourceUrl.trim() || undefined,
      });
      setManualMaterial({ title: "", sourceUrl: "", content: "" });
      setNotice("外部综合调研报告已保存，正在交给研究模型分析");
      await refresh();
      try {
        await api.analyzeManualResearchMaterials(saved.id, saved.revision);
        setNotice("外部综合调研报告已分析，等待人工确认");
      } catch (cause) {
        setError(`报告已成功导入，但分析未完成：${errorText(cause)}。可点击“重新分析已导入报告”。`);
        setNotice("报告已保存，等待重新分析");
      }
      await refresh();
    } catch (cause) {
      setError(errorText(cause));
    } finally {
      setReportImporting(false);
    }
  })();
  const analyzeManualMaterials = () => currentJob && void run("正在分析人工调研材料", () => api.analyzeManualResearchMaterials(currentJob.id, currentJob.revision));
  const generateOpportunities = () => currentJob && void run("已生成故事机会", () => api.createStoryOpportunities(currentJob.id, currentJob.revision));
  const decideOpportunity = (id: string, revision: number, action: "accept" | "reject") => void run(action === "accept" ? "已选定故事方向" : "已排除故事方向", () => api.decideStoryOpportunity(id, action, revision));
  const ensureSession = async () => {
    if (!project || !acceptedOpportunity) return null;
    return activeSession ?? api.createIdeationSession(project.id, acceptedOpportunity.id, acceptedOpportunity.revision);
  };
  const sendMessage = async () => {
    if (!message.trim()) return;
    const session = await ensureSession(); if (!session) return;
    const content = message.trim(); setMessage("");
    await run("共创意见已记录", () => api.addIdeationMessage(session.id, session.revision, content));
  };
  const generateStoryBrief = async () => { const session = await ensureSession(); if (session) await run("StoryBrief 提案已生成", () => api.createIncubationStoryBriefProposal(session.id, session.revision)); };
  const decideBrief = (action: "apply" | "reject") => pendingBriefProposal && void run(action === "apply" ? "StoryBrief 已成为当前版本" : "StoryBrief 提案已拒绝", () => api.decideIncubationStoryBriefProposal(pendingBriefProposal.id, action, pendingBriefProposal.revision));
  const generateCanon = () => project && currentStoryBrief && void run("Canon 候选已生成并完成独立分析", () => api.createIncubationCanonProposal(project.id, currentStoryBrief.revision));
  const applyCanon = () => latestCanonProposal && void run("Canon 候选已应用到草稿", () => api.applyCanonGenerationProposal(latestCanonProposal.id, latestCanonProposal.revision));
  const createExperiment = () => project && currentStoryBrief && currentCanon && void run("三个开篇实验已生成", () => api.createOpeningExperiment(project.id, currentStoryBrief.revision, currentCanon.revision));

  if (!project) return <div className="connection-state"><strong>请先选择作品</strong></div>;
  return <div className="incubator-page">
    <header className="incubator-heading"><div><span className="workbench-kicker"><Compass /> STORY DISCOVERY LAB</span><h1>故事创意孵化室</h1><p>先找到值得写的故事，再把它固化为可执行的 Canon。研究证据、你的决定与模型建议始终分开。</p></div><div className={`incubator-readiness ${readinessQuery.data?.ready ? "is-ready" : ""}`}><ShieldCheck /><div><strong>{readinessQuery.data?.ready ? "可以锁定 Canon" : "孵化尚未完成"}</strong><span>{readinessStageLabels[readinessQuery.data?.stage ?? "research_brief"] ?? "正在检查孵化状态"}</span></div></div></header>

    <nav className="incubator-rail" aria-label="创意孵化步骤">{stages.map(([label, detail], index) => <button key={label} data-testid={`incubator-stage-${index + 1}`} className={`${stage === index ? "is-active" : ""}${completed[index] ? " is-done" : ""}`} onClick={() => setStage(index)}><i>{completed[index] ? <Check /> : index + 1}</i><span><strong>{label}</strong><small>{detail}</small></span><ArrowRight /></button>)}</nav>
    {error && <div className="incubator-error"><WarningCircle /><span>{error}</span><button onClick={() => setError(null)}><X /></button></div>}
    {readinessQuery.data?.checks.some((item) => item.status === "blocked") && <div className="incubator-check-strip" aria-label="孵化阻断项">{readinessQuery.data.checks.filter((item) => item.status === "blocked").slice(0, 3).map((item) => <button key={item.code} onClick={() => item.actionPath && navigate(item.actionPath)} disabled={!item.actionPath}><WarningCircle /><span><strong>{readinessLabels[item.code] ?? "尚未完成"}</strong><small>{item.detail}</small></span>{item.actionPath && <ArrowRight />}</button>)}</div>}

    <section className="incubator-workspace">
      {stage === 0 && <div className="incubator-panel brief-lab"><header><div><Lightbulb /><span><strong>创作与调研目标</strong><small>这里不是 Canon，只是决定要研究什么</small></span></div><em>{currentBrief ? `V${currentBrief.versionNumber}` : "DRAFT"}</em></header><div className="incubator-form-grid">
        <label><span>作品形态</span><select value={briefForm.format} onChange={(e) => setBriefForm({ ...briefForm, format: e.target.value as "long-form" | "short-form" })}><option value="long-form">长篇网文</option><option value="short-form">短篇小说</option></select></label>
        <label><span>目标平台</span><input value={briefForm.platform} onChange={(e) => setBriefForm({ ...briefForm, platform: e.target.value })} /></label>
        <label><span>题材方向（可混合填写）</span><input value={briefForm.genre} onChange={(e) => setBriefForm({ ...briefForm, genre: e.target.value })} placeholder="例如：古代悬疑探案 + 女性成长 + 言情" /></label>
        <div className="incubator-field-stack"><label><span>{briefForm.format === "long-form" ? "计划章节数" : "目标总字数"}</span><input type="number" value={briefForm.targetChapters} onChange={(e) => setBriefForm({ ...briefForm, targetChapters: e.target.value })} /></label>{savedChapterMismatch && <div className="chapter-sync-note"><span>作品计划为 {project.totalChapters} 章</span>{formMatchesProjectChapters ? <small>保存后生成新的研究目标版本</small> : <button type="button" onClick={() => setBriefForm({ ...briefForm, targetChapters: String(project.totalChapters) })}>同步</button>}</div>}</div>
        <label className="wide"><span>目标读者</span><textarea value={briefForm.audience} onChange={(e) => setBriefForm({ ...briefForm, audience: e.target.value })} /></label>
        <label><span>希望提供的情绪价值（每行一个）</span><textarea value={briefForm.emotionalValue} onChange={(e) => setBriefForm({ ...briefForm, emotionalValue: e.target.value })} /></label>
        <label><span>商业目标（每行一个）</span><textarea value={briefForm.commercialGoals} onChange={(e) => setBriefForm({ ...briefForm, commercialGoals: e.target.value })} /></label>
        <label><span>限定研究网站/域名（每行一个，可选）</span><textarea value={briefForm.includedDomains} onChange={(e) => setBriefForm({ ...briefForm, includedDomains: e.target.value })} placeholder={"留空则广搜公开网页；例如：zhihu.com\nxiaohongshu.com"} /></label>
        <label><span>排除网站/域名（每行一个，可选）</span><textarea value={briefForm.excludedDomains} onChange={(e) => setBriefForm({ ...briefForm, excludedDomains: e.target.value })} placeholder="不希望进入证据范围的网站" /></label>
        <label><span>参考作品（只研究抽象机制）</span><textarea value={briefForm.referenceWorks} onChange={(e) => setBriefForm({ ...briefForm, referenceWorks: e.target.value })} /></label>
        <label><span>明确禁写内容</span><textarea value={briefForm.forbiddenContent} onChange={(e) => setBriefForm({ ...briefForm, forbiddenContent: e.target.value })} /></label>
        <label className="wide"><span>补充说明</span><textarea value={briefForm.notes} onChange={(e) => setBriefForm({ ...briefForm, notes: e.target.value })} /></label>
      </div><footer><span>保存后仍可继续修改；新版本会使旧研究任务失效，避免混用结论。</span><button className="gold-action" disabled={mutation.isPending || !briefForm.genre.trim() || !briefForm.audience.trim() || !targetAmountValid} onClick={saveBrief}><Check />保存并进入调研</button></footer></div>}

      {stage === 1 && <div className="research-layout"><main className="incubator-panel research-console"><header><div><MagnifyingGlass /><span><strong>市场证据工作台</strong><small>Tavily 发现公开页面 · Firecrawl 提取可访问正文 · DeepSeek 归纳证据</small></span></div><em>{currentJob?.status ?? "NOT STARTED"}</em></header><div className="research-scope-note"><ShieldCheck /><span>仅研究公开网页；登录、付费墙或反爬页面可能无法读取。留空则广搜，填写限定域名后只研究这些网站。</span></div>{!currentJob ? <div className="provider-key-grid"><label><span>Tavily API Key</span><input type="password" value={researchKeys.tavily} onChange={(e) => setResearchKeys({ ...researchKeys, tavily: e.target.value })} placeholder="首次使用需要，保存到 Windows 凭据管理器" /></label><label><span>Firecrawl API Key</span><input type="password" value={researchKeys.firecrawl} onChange={(e) => setResearchKeys({ ...researchKeys, firecrawl: e.target.value })} placeholder="首次使用需要，页面和 API 都不会回显" /></label><button className="gold-action" onClick={startResearch} disabled={!currentBrief || mutation.isPending}>{mutation.isPending ? <CircleNotch className="spin" /> : <MagnifyingGlass />}开始真实调研</button></div> : <>
        {researchNeedsRecovery && <div className="provider-key-grid provider-key-recovery"><label><span>更新 Tavily API Key（可选）</span><input type="password" value={researchKeys.tavily} onChange={(e) => setResearchKeys({ ...researchKeys, tavily: e.target.value })} placeholder="留空则继续使用凭据管理器中的值" /></label><label><span>更新 Firecrawl API Key（可选）</span><input type="password" value={researchKeys.firecrawl} onChange={(e) => setResearchKeys({ ...researchKeys, firecrawl: e.target.value })} placeholder="完整密钥不会回显" /></label><button onClick={startResearch} disabled={mutation.isPending || (!researchKeys.tavily && !researchKeys.firecrawl)}>更新凭据</button></div>}
        {currentJob.errorCode && <div className="research-job-error"><WarningCircle /><div><strong>{currentJob.errorCode}</strong><span>{researchErrorMessages[currentJob.errorCode] ?? currentJob.errorMessage ?? "研究任务需要处理后才能恢复。"}</span></div></div>}
        <div className="research-metrics"><article><span>查询</span><strong>{currentJob.queryCount}</strong></article><article><span>来源页面</span><strong>{currentJob.pageCount}</strong></article><article><span>证据片段</span><strong>{evidenceQuery.data?.length ?? 0}</strong></article><article><span>预计费用</span><strong>¥ / ${currentJob.estimatedCost.toFixed(4)}</strong></article></div>
        <section className="research-run-trace" aria-label="调研运行轨迹">
          <header><span>当前阶段</span><strong>{researchStages[currentJob.status] ?? currentJob.status}</strong><small>搜索结果 {Number(currentJob.coverage.searchResultCount ?? 0)} · 发现来源 {Number(currentJob.coverage.discoveredSourceCount ?? 0)} · 抓取失败 {Number(currentJob.coverage.failedFetchCount ?? 0)}</small></header>
          {currentJob.errorCode && <p>{researchFailureHelp[currentJob.errorCode] ?? currentJob.errorMessage}</p>}
          <ol>{researchQueriesQuery.data?.map((item) => <li key={item.id} className={`is-${item.status}`}><span>{perspectiveLabels[item.perspective] ?? item.perspective}</span><strong>{item.status === "failed" ? item.errorCode ?? "失败" : item.status === "succeeded" ? `${item.resultCount} 条结果` : item.status}</strong><small>{item.query}</small></li>)}</ol>
        </section>
        <details className="manual-research-entry" open><summary>导入外部综合调研报告</summary><p>把其他 Agent 或你自己的完整调研结论直接粘贴在这里。系统将它保存为“外部综合报告”来源，再由研究模型拆解证据、竞品机制与故事机会；不会调用 Tavily 或 Firecrawl，分析结果仍需你人工接受。</p><div><label>报告标题（可选）<input value={manualMaterial.title} onChange={(event) => setManualMaterial({ ...manualMaterial, title: event.target.value })} placeholder="例如：女性读者偏好与古代悬疑竞品调研" /></label><label>来源说明或公开链接（可选）<input value={manualMaterial.sourceUrl} onChange={(event) => setManualMaterial({ ...manualMaterial, sourceUrl: event.target.value })} placeholder="https://..." /></label><label>完整调研报告<textarea value={manualMaterial.content} onChange={(event) => setManualMaterial({ ...manualMaterial, content: event.target.value })} placeholder="粘贴完整调研结果：读者偏好、竞品、平台趋势、开篇建议、风险与不确定性均可由模型自行拆解。" /></label></div><footer>{currentJob.pageCount > 0 && <button onClick={analyzeManualMaterials} disabled={mutation.isPending || reportImporting}>重新分析已导入报告</button>}<button className="accept" onClick={importAndAnalyzeResearchReport} disabled={mutation.isPending || reportImporting || manualMaterial.content.trim().length < 300}>{reportImporting ? "正在导入并分析" : "导入并分析报告"}</button></footer></details>
        <div className="research-actions">{["failed", "cancelled", "insufficient_evidence"].includes(currentJob.status) && <button onClick={() => actOnJob("resume")}>恢复任务</button>}{["planning", "searching", "fetching", "analyzing"].includes(currentJob.status) && <button onClick={() => actOnJob("cancel")}>取消</button>}{currentJob.status === "awaiting_review" && <><button className="accept" onClick={() => actOnJob("accept")}><Check />接受研究报告</button><button onClick={() => actOnJob("reject")}><X />拒绝</button></>}</div>
        <div className="research-columns"><section><h3>竞品机制 <b>{competitorsQuery.data?.length ?? 0}</b></h3>{competitorsQuery.data?.slice(0, 6).map((item) => <article key={item.id}><strong>{item.name}</strong><span>{Math.round(item.confidence * 100)}% 可信度 · {item.evidenceIds.length} 条证据</span></article>)}</section><section><h3>研究发现 <b>{findingsQuery.data?.length ?? 0}</b></h3>{findingsQuery.data?.slice(0, 8).map((item) => <article key={item.id}><strong>{item.statement}</strong><span>{item.claimType} · {item.evidenceIds.length} 条引用</span></article>)}</section></div>
      </>}</main><aside className="incubator-panel evidence-drawer"><header><div><Books /><span><strong>证据抽屉</strong><small>可追溯到冻结来源版本</small></span></div></header>{evidenceQuery.data?.slice(0, 12).map((item) => <article key={item.id}><span className={`claim-${item.claimType}`}>{item.claimType}</span><p>{item.claim}</p><blockquote>{item.excerpt}</blockquote></article>)}</aside></div>}

      {stage === 2 && <div className="incubator-panel opportunity-deck"><header><div><Sparkle /><span><strong>故事机会候选</strong><small>分数用于比较，不代替你的判断</small></span></div>{currentJob?.status === "accepted" && !opportunitiesQuery.data?.length && <button className="gold-action" onClick={generateOpportunities} disabled={mutation.isPending}><Sparkle />生成 3 个方向</button>}</header><div className="opportunity-grid">{opportunitiesQuery.data?.map((item, index) => <article key={item.id} className={item.status === "accepted" ? "is-accepted" : ""}><header><span>方向 {String(index + 1).padStart(2, "0")}</span><strong>{item.totalScore}<small>/100</small></strong></header><h2>{item.highConcept}</h2><dl><div><dt>主角欲望</dt><dd>{String(item.story.coreDesire ?? "未建立")}</dd></div><div><dt>核心冲突</dt><dd>{String(item.story.coreConflict ?? "未建立")}</dd></div><div><dt>连载发动机</dt><dd>{String(item.story.serialEngine ?? "未建立")}</dd></div></dl><footer><span>{Math.round(item.evidenceCoverage * 100)}% 证据覆盖</span>{item.status === "pending" && <div><button onClick={() => decideOpportunity(item.id, item.revision, "reject")}><X />排除</button><button className="accept" onClick={() => decideOpportunity(item.id, item.revision, "accept")}><Check />选这个方向</button></div>}{item.status === "accepted" && <b><CheckCircle />当前方向</b>}</footer></article>)}</div>{!opportunitiesQuery.data?.length && <div className="incubator-empty"><Lightbulb /><strong>先接受研究报告，再让模型基于证据提出真正不同的故事方向。</strong></div>}</div>}

      {stage === 3 && <div className="ideation-layout"><aside className="incubator-panel decision-ledger"><header><div><Brain /><span><strong>共创台账</strong><small>模型建议不会自动变成正式设定</small></span></div></header>{["confirmedDecisions", "openQuestions", "aiSuggestions", "conflicts"].map((key) => <section key={key}><h3>{key}</h3>{((activeSession?.state[key] as unknown[]) ?? []).map((item, index) => <p key={index}>{String(item)}</p>)}</section>)}</aside><main className="incubator-panel ideation-chat"><header><div><Sparkle /><span><strong>和故事策划 Agent 讨论</strong><small>{acceptedOpportunity?.highConcept ?? "请先选择一个故事方向"}</small></span></div><em>{activeSession ? `REV ${activeSession.revision}` : "NEW"}</em></header><div className="ideation-messages">{activeSession?.messages.map((item) => <article key={item.id} className={`is-${item.role}`}><strong>{item.role === "user" ? "你" : "故事策划"}</strong><p>{item.content}</p></article>)}{!activeSession?.messages.length && <div className="incubator-empty"><Brain /><strong>先说出你真正想写什么、最不想要什么，至少讨论两三轮。</strong></div>}</div><footer><textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="例如：这个方向太冷，我希望主角第一章就做一个让读者心疼但佩服的选择……" /><button className="gold-action" onClick={() => void sendMessage()} disabled={!acceptedOpportunity || !message.trim() || mutation.isPending}><PaperPlaneTilt />发送</button></footer></main></div>}

      {stage === 4 && <div className="incubator-panel storybrief-review"><header><div><LockKey /><span><strong>StoryBrief 决策闸门</strong><small>这是 Canon 的上游合同，不确认就不会向下游写入</small></span></div>{activeSession && !pendingBriefProposal && !currentStoryBrief && <button className="gold-action" onClick={() => void generateStoryBrief()} disabled={mutation.isPending || ideationUserTurns < 2}><Sparkle />生成 StoryBrief 提案 · {ideationUserTurns}/2 轮</button>}</header>{pendingBriefProposal ? <><div className="storybrief-json"><pre>{jsonPreview(pendingBriefProposal.proposedBrief)}</pre></div><footer><button onClick={() => decideBrief("reject")}><X />拒绝</button><button className="accept" onClick={() => decideBrief("apply")}><Check />确认成为当前 StoryBrief</button></footer></> : currentStoryBrief ? <><div className="brief-authority"><CheckCircle /><div><strong>StoryBrief V{currentStoryBrief.versionNumber} 已生效</strong><span>Checksum {currentStoryBrief.checksum.slice(0, 12)} · 后续 Canon 必须从此版本生成</span></div></div><div className="storybrief-json"><pre>{jsonPreview(currentStoryBrief.brief)}</pre></div></> : <div className="incubator-empty"><LockKey /><strong>{ideationUserTurns < 2 ? `至少完成两轮真实讨论后再冻结 StoryBrief；当前 ${ideationUserTurns}/2 轮。` : "共创讨论已达到最低轮次，可以生成提案；你仍需要人工确认。"}</strong></div>}</div>}

      {stage === 5 && <div className="canon-opening-layout"><section className="incubator-panel canon-candidate"><header><div><ShieldCheck /><span><strong>通用 Canon 候选</strong><small>独立 Analyzer 交叉校验，失败提案不能应用</small></span></div>{currentStoryBrief && !latestCanonProposal && <button className="gold-action" onClick={generateCanon} disabled={mutation.isPending}><Sparkle />生成 Canon 候选</button>}</header>{latestCanonProposal ? <><div className={`canon-verdict ${latestCanonProposal.readiness.ready ? "is-ready" : "is-blocked"}`}><strong>{latestCanonProposal.readiness.ready ? "完整性通过" : "候选被阻断"}</strong><span>{latestCanonProposal.readiness.checks.filter((item) => item.status !== "ready").length} 个待处理项</span></div><div className="architecture-check-grid">{latestCanonProposal.readiness.checks.map((item) => <span key={item.code} className={`is-${item.status}`}>{item.status === "ready" ? <Check /> : <WarningCircle />}{item.code}</span>)}</div><details><summary>查看 Canon Markdown</summary><pre>{latestCanonProposal.contentMarkdown}</pre></details>{latestCanonProposal.status === "pending" && <footer><button className="accept" disabled={!latestCanonProposal.readiness.ready} onClick={applyCanon}><Check />应用到 Canon 草稿</button></footer>}</> : <div className="incubator-empty"><ShieldCheck /><strong>先确认 StoryBrief，再生成符合当前题材的结构化 Canon。</strong></div>}</section>
        <section className="incubator-panel opening-arena"><header><div><Flask /><span><strong>三开篇实验场</strong><small>强事件、强人物、强悬念分别生成并独立评审</small></span></div>{currentStoryBrief && currentCanon && !latestExperiment && <button className="gold-action" onClick={createExperiment} disabled={mutation.isPending || canonQuery.data?.locked}><Flask />生成三个开篇</button>}</header><div className="opening-grid">{latestExperiment?.candidates.map((candidate) => <article key={candidate.id} className={candidate.status === "selected" ? "is-selected" : ""}><header><span>{candidate.strategyLabel}</span><b>{candidate.evaluations.find((item) => item.reviewerRole === "reader_simulator")?.scores.continueReading ?? "—"}</b></header><h3>{candidate.chapters[0]?.title}</h3><p>{candidate.chapters[0]?.content.slice(0, 220)}…</p><div>{candidate.evaluations.map((review) => <span key={review.id}>{review.reviewerRole}: {review.recommendation}</span>)}</div>{candidate.status === "candidate" && <footer><button onClick={() => latestExperiment && void run("开篇方向已选中", () => api.decideOpeningCandidate(candidate.id, "select", candidate.revision, latestExperiment.revision))}><Check />选择方向</button></footer>}{candidate.status === "selected" && candidate.chapterCount === 1 && <footer><button onClick={() => latestExperiment && void run("已扩写为三章实验稿", () => api.expandOpeningExperiment(latestExperiment.id, candidate.id, latestExperiment.revision, candidate.revision))}>扩写第 2—3 章</button></footer>}{candidate.status === "selected" && candidate.chapterCount === 3 && <footer className="chapter-approvals">{candidate.chapters.map((chapter) => <button key={chapter.chapterNumber} disabled={chapter.manualApproved} onClick={() => void run(`第 ${chapter.chapterNumber} 章实验稿已批准`, () => api.approveOpeningChapter(candidate.id, chapter.chapterNumber, candidate.revision))}>{chapter.manualApproved ? <CheckCircle /> : <Check />}{chapter.chapterNumber}章</button>)}</footer>}</article>)}</div>{!latestExperiment && <div className="incubator-empty"><Flask /><strong>Canon 应用为草稿后，先比较三个真实开头，不要直接开始连载。</strong></div>}</section></div>}
    </section>
  </div>;
}
