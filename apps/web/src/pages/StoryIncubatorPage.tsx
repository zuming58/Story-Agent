import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight, Books, Brain, Check, CheckCircle, CircleNotch, Compass, Flask,
  Lightbulb, LockKey, MagnifyingGlass, PaperPlaneTilt, ShieldCheck, Sparkle, WarningCircle, X,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { api, ApiClientError } from "../api/client";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";

const stages = [
  ["研究目标", "先说清楚写给谁看"], ["市场调研", "证据不是模型印象"], ["故事机会", "比较三到五个方向"],
  ["人机共创", "讨论到你真正认可"], ["StoryBrief", "冻结创作承诺"], ["Canon 与开篇", "三种开头先试后定"],
] as const;

function lines(value: string) { return value.split(/\r?\n|,/).map((item) => item.trim()).filter(Boolean); }
function errorText(error: unknown) {
  if (error instanceof ApiClientError) return `${error.payload.code}：${error.payload.message}`;
  return error instanceof Error ? error.message : "操作失败";
}
function jsonPreview(value: unknown) { return JSON.stringify(value ?? {}, null, 2); }

export function StoryIncubatorPage() {
  const { project } = useStoryWorkspace();
  const client = useQueryClient();
  const setNotice = useStoryStore((state) => state.setNotice);
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const [stage, setStage] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [researchKeys, setResearchKeys] = useState({ tavily: "", firecrawl: "" });
  const [message, setMessage] = useState("");
  const [briefForm, setBriefForm] = useState({
    format: "long-form" as "long-form" | "short-form", platform: "番茄小说", genre: "现代中式悬疑",
    audience: "喜欢强钩子、具体人物欲望和持续悬念的成年读者", targetChapters: "120",
    emotionalValue: "紧张\n好奇\n情绪释放", includedDomains: "", excludedDomains: "",
    referenceWorks: "", forbiddenContent: "不模仿具体作者原文\n不以堆设定代替剧情", commercialGoals: "前三章留存\n稳定追读",
    notes: "先研究读者为什么继续读、为什么弃书，再讨论故事。",
  });

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

  const evidenceQuery = useQuery({ queryKey: ["incubator-evidence", currentJob?.id], queryFn: () => api.researchEvidence(currentJob!.id), enabled: Boolean(currentJob) });
  const competitorsQuery = useQuery({ queryKey: ["incubator-competitors", currentJob?.id], queryFn: () => api.researchCompetitors(currentJob!.id), enabled: Boolean(currentJob) });
  const findingsQuery = useQuery({ queryKey: ["incubator-findings", currentJob?.id], queryFn: () => api.researchFindings(currentJob!.id), enabled: Boolean(currentJob) });

  const completed = useMemo(() => [
    Boolean(currentBrief), currentJob?.status === "accepted", Boolean(acceptedOpportunity), Boolean(activeSession?.messages.length),
    Boolean(currentStoryBrief), Boolean(readinessQuery.data?.ready),
  ], [currentBrief, currentJob?.status, acceptedOpportunity, activeSession?.messages.length, currentStoryBrief, readinessQuery.data?.ready]);

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
    void run("市场调研已完成或进入待审阅状态", () => api.createResearchJob(project.id, {
      briefId: currentBrief.id, expectedBriefRevision: currentBrief.revision, idempotencyKey: `research:${currentBrief.checksum}`,
      searchProvider: "tavily", fetchProvider: "firecrawl", searchApiKey: researchKeys.tavily || undefined, fetchApiKey: researchKeys.firecrawl || undefined,
      runImmediately: true, limits: { maxQueries: 6, maxPages: 24, maxTotalChars: 160000, maxCost: 8, maxRuntimeSeconds: 900, minimumSourceTypes: 3 },
    }));
  };
  const actOnJob = (action: "run" | "resume" | "cancel" | "accept" | "reject") => currentJob && void run(`研究任务已${action === "accept" ? "接受" : action === "reject" ? "拒绝" : "更新"}`, () => api.researchJobAction(currentJob.id, action, currentJob.revision));
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
    <header className="incubator-heading"><div><span className="workbench-kicker"><Compass /> STORY DISCOVERY LAB</span><h1>故事创意孵化室</h1><p>先找到值得写的故事，再把它固化为可执行的 Canon。研究证据、你的决定与模型建议始终分开。</p></div><div className={`incubator-readiness ${readinessQuery.data?.ready ? "is-ready" : ""}`}><ShieldCheck /><div><strong>{readinessQuery.data?.ready ? "可以锁定 Canon" : "孵化尚未完成"}</strong><span>{readinessQuery.data?.stage ?? "research_brief"}</span></div></div></header>

    <nav className="incubator-rail" aria-label="创意孵化步骤">{stages.map(([label, detail], index) => <button key={label} className={`${stage === index ? "is-active" : ""}${completed[index] ? " is-done" : ""}`} onClick={() => setStage(index)}><i>{completed[index] ? <Check /> : index + 1}</i><span><strong>{label}</strong><small>{detail}</small></span><ArrowRight /></button>)}</nav>
    {error && <div className="incubator-error"><WarningCircle /><span>{error}</span><button onClick={() => setError(null)}><X /></button></div>}

    <section className="incubator-workspace">
      {stage === 0 && <div className="incubator-panel brief-lab"><header><div><Lightbulb /><span><strong>创作与调研目标</strong><small>这里不是 Canon，只是决定要研究什么</small></span></div><em>{currentBrief ? `V${currentBrief.versionNumber}` : "DRAFT"}</em></header><div className="incubator-form-grid">
        <label><span>作品形态</span><select value={briefForm.format} onChange={(e) => setBriefForm({ ...briefForm, format: e.target.value as "long-form" | "short-form" })}><option value="long-form">长篇网文</option><option value="short-form">短篇小说</option></select></label>
        <label><span>目标平台</span><input value={briefForm.platform} onChange={(e) => setBriefForm({ ...briefForm, platform: e.target.value })} /></label>
        <label><span>题材方向</span><input value={briefForm.genre} onChange={(e) => setBriefForm({ ...briefForm, genre: e.target.value })} /></label>
        <label><span>{briefForm.format === "long-form" ? "计划章节数" : "目标总字数"}</span><input type="number" value={briefForm.targetChapters} onChange={(e) => setBriefForm({ ...briefForm, targetChapters: e.target.value })} /></label>
        <label className="wide"><span>目标读者</span><textarea value={briefForm.audience} onChange={(e) => setBriefForm({ ...briefForm, audience: e.target.value })} /></label>
        <label><span>希望提供的情绪价值（每行一个）</span><textarea value={briefForm.emotionalValue} onChange={(e) => setBriefForm({ ...briefForm, emotionalValue: e.target.value })} /></label>
        <label><span>商业目标（每行一个）</span><textarea value={briefForm.commercialGoals} onChange={(e) => setBriefForm({ ...briefForm, commercialGoals: e.target.value })} /></label>
        <label><span>参考作品（只研究抽象机制）</span><textarea value={briefForm.referenceWorks} onChange={(e) => setBriefForm({ ...briefForm, referenceWorks: e.target.value })} /></label>
        <label><span>明确禁写内容</span><textarea value={briefForm.forbiddenContent} onChange={(e) => setBriefForm({ ...briefForm, forbiddenContent: e.target.value })} /></label>
        <label className="wide"><span>补充说明</span><textarea value={briefForm.notes} onChange={(e) => setBriefForm({ ...briefForm, notes: e.target.value })} /></label>
      </div><footer><span>保存后仍可继续修改；新版本会使旧研究任务失效，避免混用结论。</span><button className="gold-action" disabled={mutation.isPending || !briefForm.genre || !briefForm.audience} onClick={saveBrief}><Check />保存并进入调研</button></footer></div>}

      {stage === 1 && <div className="research-layout"><main className="incubator-panel research-console"><header><div><MagnifyingGlass /><span><strong>市场证据工作台</strong><small>搜索与正文提取由专用 Provider 完成，DeepSeek 负责分析</small></span></div><em>{currentJob?.status ?? "NOT STARTED"}</em></header>{!currentJob ? <div className="provider-key-grid"><label><span>Tavily API Key</span><input type="password" value={researchKeys.tavily} onChange={(e) => setResearchKeys({ ...researchKeys, tavily: e.target.value })} placeholder="首次使用需要，保存到 Windows 凭据管理器" /></label><label><span>Firecrawl API Key</span><input type="password" value={researchKeys.firecrawl} onChange={(e) => setResearchKeys({ ...researchKeys, firecrawl: e.target.value })} placeholder="首次使用需要，页面和 API 都不会回显" /></label><button className="gold-action" onClick={startResearch} disabled={!currentBrief || mutation.isPending}>{mutation.isPending ? <CircleNotch className="spin" /> : <MagnifyingGlass />}开始真实调研</button></div> : <>
        <div className="research-metrics"><article><span>查询</span><strong>{currentJob.queryCount}</strong></article><article><span>来源页面</span><strong>{currentJob.pageCount}</strong></article><article><span>证据片段</span><strong>{evidenceQuery.data?.length ?? 0}</strong></article><article><span>预计费用</span><strong>¥ / ${currentJob.estimatedCost.toFixed(4)}</strong></article></div>
        <div className="research-actions">{["failed", "cancelled", "insufficient_evidence"].includes(currentJob.status) && <button onClick={() => actOnJob("resume")}>恢复任务</button>}{["planning", "searching", "fetching", "analyzing"].includes(currentJob.status) && <button onClick={() => actOnJob("cancel")}>取消</button>}{currentJob.status === "awaiting_review" && <><button className="accept" onClick={() => actOnJob("accept")}><Check />接受研究报告</button><button onClick={() => actOnJob("reject")}><X />拒绝</button></>}</div>
        <div className="research-columns"><section><h3>竞品机制 <b>{competitorsQuery.data?.length ?? 0}</b></h3>{competitorsQuery.data?.slice(0, 6).map((item) => <article key={item.id}><strong>{item.name}</strong><span>{Math.round(item.confidence * 100)}% 可信度 · {item.evidenceIds.length} 条证据</span></article>)}</section><section><h3>研究发现 <b>{findingsQuery.data?.length ?? 0}</b></h3>{findingsQuery.data?.slice(0, 8).map((item) => <article key={item.id}><strong>{item.statement}</strong><span>{item.claimType} · {item.evidenceIds.length} 条引用</span></article>)}</section></div>
      </>}</main><aside className="incubator-panel evidence-drawer"><header><div><Books /><span><strong>证据抽屉</strong><small>可追溯到冻结来源版本</small></span></div></header>{evidenceQuery.data?.slice(0, 12).map((item) => <article key={item.id}><span className={`claim-${item.claimType}`}>{item.claimType}</span><p>{item.claim}</p><blockquote>{item.excerpt}</blockquote></article>)}</aside></div>}

      {stage === 2 && <div className="incubator-panel opportunity-deck"><header><div><Sparkle /><span><strong>故事机会候选</strong><small>分数用于比较，不代替你的判断</small></span></div>{currentJob?.status === "accepted" && !opportunitiesQuery.data?.length && <button className="gold-action" onClick={generateOpportunities} disabled={mutation.isPending}><Sparkle />生成 3—5 个方向</button>}</header><div className="opportunity-grid">{opportunitiesQuery.data?.map((item, index) => <article key={item.id} className={item.status === "accepted" ? "is-accepted" : ""}><header><span>方向 {String(index + 1).padStart(2, "0")}</span><strong>{item.totalScore}<small>/100</small></strong></header><h2>{item.highConcept}</h2><dl><div><dt>主角欲望</dt><dd>{String(item.story.coreDesire ?? "未建立")}</dd></div><div><dt>核心冲突</dt><dd>{String(item.story.coreConflict ?? "未建立")}</dd></div><div><dt>连载发动机</dt><dd>{String(item.story.serialEngine ?? "未建立")}</dd></div></dl><footer><span>{Math.round(item.evidenceCoverage * 100)}% 证据覆盖</span>{item.status === "pending" && <div><button onClick={() => decideOpportunity(item.id, item.revision, "reject")}><X />排除</button><button className="accept" onClick={() => decideOpportunity(item.id, item.revision, "accept")}><Check />选这个方向</button></div>}{item.status === "accepted" && <b><CheckCircle />当前方向</b>}</footer></article>)}</div>{!opportunitiesQuery.data?.length && <div className="incubator-empty"><Lightbulb /><strong>先接受研究报告，再让模型基于证据提出真正不同的故事方向。</strong></div>}</div>}

      {stage === 3 && <div className="ideation-layout"><aside className="incubator-panel decision-ledger"><header><div><Brain /><span><strong>共创台账</strong><small>模型建议不会自动变成正式设定</small></span></div></header>{["confirmedDecisions", "openQuestions", "aiSuggestions", "conflicts"].map((key) => <section key={key}><h3>{key}</h3>{((activeSession?.state[key] as unknown[]) ?? []).map((item, index) => <p key={index}>{String(item)}</p>)}</section>)}</aside><main className="incubator-panel ideation-chat"><header><div><Sparkle /><span><strong>和故事策划 Agent 讨论</strong><small>{acceptedOpportunity?.highConcept ?? "请先选择一个故事方向"}</small></span></div><em>{activeSession ? `REV ${activeSession.revision}` : "NEW"}</em></header><div className="ideation-messages">{activeSession?.messages.map((item) => <article key={item.id} className={`is-${item.role}`}><strong>{item.role === "user" ? "你" : "故事策划"}</strong><p>{item.content}</p></article>)}{!activeSession?.messages.length && <div className="incubator-empty"><Brain /><strong>先说出你真正想写什么、最不想要什么，至少讨论两三轮。</strong></div>}</div><footer><textarea value={message} onChange={(e) => setMessage(e.target.value)} placeholder="例如：这个方向太冷，我希望主角第一章就做一个让读者心疼但佩服的选择……" /><button className="gold-action" onClick={() => void sendMessage()} disabled={!acceptedOpportunity || !message.trim() || mutation.isPending}><PaperPlaneTilt />发送</button></footer></main></div>}

      {stage === 4 && <div className="incubator-panel storybrief-review"><header><div><LockKey /><span><strong>StoryBrief 决策闸门</strong><small>这是 Canon 的上游合同，不确认就不会向下游写入</small></span></div>{activeSession && !pendingBriefProposal && !currentStoryBrief && <button className="gold-action" onClick={() => void generateStoryBrief()} disabled={mutation.isPending}><Sparkle />生成 StoryBrief 提案</button>}</header>{pendingBriefProposal ? <><div className="storybrief-json"><pre>{jsonPreview(pendingBriefProposal.proposedBrief)}</pre></div><footer><button onClick={() => decideBrief("reject")}><X />拒绝</button><button className="accept" onClick={() => decideBrief("apply")}><Check />确认成为当前 StoryBrief</button></footer></> : currentStoryBrief ? <><div className="brief-authority"><CheckCircle /><div><strong>StoryBrief V{currentStoryBrief.versionNumber} 已生效</strong><span>Checksum {currentStoryBrief.checksum.slice(0, 12)} · 后续 Canon 必须从此版本生成</span></div></div><div className="storybrief-json"><pre>{jsonPreview(currentStoryBrief.brief)}</pre></div></> : <div className="incubator-empty"><LockKey /><strong>完成共创讨论后生成提案。你仍需要人工确认。</strong></div>}</div>}

      {stage === 5 && <div className="canon-opening-layout"><section className="incubator-panel canon-candidate"><header><div><ShieldCheck /><span><strong>通用 Canon 候选</strong><small>独立 Analyzer 交叉校验，失败提案不能应用</small></span></div>{currentStoryBrief && !latestCanonProposal && <button className="gold-action" onClick={generateCanon} disabled={mutation.isPending}><Sparkle />生成 Canon 候选</button>}</header>{latestCanonProposal ? <><div className={`canon-verdict ${latestCanonProposal.readiness.ready ? "is-ready" : "is-blocked"}`}><strong>{latestCanonProposal.readiness.ready ? "完整性通过" : "候选被阻断"}</strong><span>{latestCanonProposal.readiness.checks.filter((item) => item.status !== "ready").length} 个待处理项</span></div><div className="architecture-check-grid">{latestCanonProposal.readiness.checks.map((item) => <span key={item.code} className={`is-${item.status}`}>{item.status === "ready" ? <Check /> : <WarningCircle />}{item.code}</span>)}</div><details><summary>查看 Canon Markdown</summary><pre>{latestCanonProposal.contentMarkdown}</pre></details>{latestCanonProposal.status === "pending" && <footer><button className="accept" disabled={!latestCanonProposal.readiness.ready} onClick={applyCanon}><Check />应用到 Canon 草稿</button></footer>}</> : <div className="incubator-empty"><ShieldCheck /><strong>先确认 StoryBrief，再生成符合当前题材的结构化 Canon。</strong></div>}</section>
        <section className="incubator-panel opening-arena"><header><div><Flask /><span><strong>三开篇实验场</strong><small>强事件、强人物、强悬念分别生成并独立评审</small></span></div>{currentStoryBrief && currentCanon && !latestExperiment && <button className="gold-action" onClick={createExperiment} disabled={mutation.isPending || canonQuery.data?.locked}><Flask />生成三个开篇</button>}</header><div className="opening-grid">{latestExperiment?.candidates.map((candidate) => <article key={candidate.id} className={candidate.status === "selected" ? "is-selected" : ""}><header><span>{candidate.strategyLabel}</span><b>{candidate.evaluations.find((item) => item.reviewerRole === "reader_simulator")?.scores.continueReading ?? "—"}</b></header><h3>{candidate.chapters[0]?.title}</h3><p>{candidate.chapters[0]?.content.slice(0, 220)}…</p><div>{candidate.evaluations.map((review) => <span key={review.id}>{review.reviewerRole}: {review.recommendation}</span>)}</div>{candidate.status === "candidate" && <footer><button onClick={() => latestExperiment && void run("开篇方向已选中", () => api.decideOpeningCandidate(candidate.id, "select", candidate.revision, latestExperiment.revision))}><Check />选择方向</button></footer>}{candidate.status === "selected" && candidate.chapterCount === 1 && <footer><button onClick={() => latestExperiment && void run("已扩写为三章实验稿", () => api.expandOpeningExperiment(latestExperiment.id, candidate.id, latestExperiment.revision, candidate.revision))}>扩写第 2—3 章</button></footer>}{candidate.status === "selected" && candidate.chapterCount === 3 && <footer className="chapter-approvals">{candidate.chapters.map((chapter) => <button key={chapter.chapterNumber} disabled={chapter.manualApproved} onClick={() => void run(`第 ${chapter.chapterNumber} 章实验稿已批准`, () => api.approveOpeningChapter(candidate.id, chapter.chapterNumber, candidate.revision))}>{chapter.manualApproved ? <CheckCircle /> : <Check />}{chapter.chapterNumber}章</button>)}</footer>}</article>)}</div>{!latestExperiment && <div className="incubator-empty"><Flask /><strong>Canon 应用为草稿后，先比较三个真实开头，不要直接开始连载。</strong></div>}</section></div>}
    </section>
  </div>;
}
