import { useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise, BookOpenText, CheckCircle, CircleNotch, FileText, FloppyDisk,
  GitDiff, LockKey, MagicWand, Play, Prohibit, Sparkle, Stop, Target, Timer,
  WarningCircle,
} from "@phosphor-icons/react";
import { useChapterWorkspace } from "../hooks/useChapterWorkspace";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";
import type { ChapterContract, ChapterJobStatus } from "../types";

const statusLabels: Record<ChapterJobStatus, string> = {
  queued: "待执行", compiling_context: "编译上下文", drafting: "生成正文", extracting: "抽取事实",
  validating: "硬规则校验", reviewing: "多角色复核", revising: "修订中", human_review: "待复核",
  approved: "已批准", completed: "已提交", failed: "失败", cancel_requested: "停止中", cancelled: "已停止", interrupted: "已中断",
};

function listText(value: string[]) { return value.join("\n"); }
function lines(value: string) { return value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean); }

export function ChapterWritingPage() {
  const workspace = useChapterWorkspace();
  const { streamPreview } = useStoryWorkspace();
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const [authorNote, setAuthorNote] = useState("");
  const [draftText, setDraftText] = useState("");
  const [editReason, setEditReason] = useState("");
  const [selectionRange, setSelectionRange] = useState<{ start: number; end: number } | null>(null);
  const [contractForm, setContractForm] = useState({ title: "", pov: "", targetWordsMin: 2200, targetWordsMax: 3200, pace: "smooth", requiredCharacters: "", requiredForeshadows: "", requiredHooks: "", completionConditions: "" });

  useEffect(() => {
    const contract = workspace.currentContract;
    if (!contract) return;
    setContractForm({
      title: contract.title, pov: contract.pov, targetWordsMin: contract.targetWordsMin, targetWordsMax: contract.targetWordsMax,
      pace: contract.pace, requiredCharacters: listText(contract.requiredCharacters), requiredForeshadows: listText(contract.requiredForeshadows),
      requiredHooks: listText(contract.requiredHooks), completionConditions: listText(contract.completionConditions),
    });
  }, [workspace.currentContract?.id, workspace.currentContract?.revision]);

  useEffect(() => setDraftText(workspace.currentDraft?.contentMarkdown ?? ""), [workspace.currentDraft?.id, workspace.currentDraft?.revision]);

  useEffect(() => {
    setAgentContext([
      `第${workspace.chapterNumber}章`,
      workspace.currentContract?.status === "locked" ? "契约已锁定" : "契约草稿",
      workspace.currentDraft ? `正文 v${workspace.currentDraft.versionNumber}` : "尚无正文",
    ]);
    return () => setAgentContext([]);
  }, [workspace.chapterNumber, workspace.currentContract?.status, workspace.currentDraft?.versionNumber, setAgentContext]);

  const chapterNumbers = useMemo(() => {
    const total = workspace.project?.totalChapters ?? 100;
    const start = Math.max(1, Math.min(workspace.chapterNumber - 5, total - 13));
    return Array.from({ length: Math.min(14, total) }, (_, index) => start + index);
  }, [workspace.chapterNumber, workspace.project?.totalChapters]);

  const dirty = Boolean(workspace.currentDraft && draftText !== workspace.currentDraft.contentMarkdown);
  const previousDraft = workspace.drafts.find((item) => item.versionNumber === (workspace.currentDraft?.versionNumber ?? 1) - 1);
  const active = workspace.currentJob && ["compiling_context", "drafting", "extracting", "validating", "reviewing", "revising", "cancel_requested"].includes(workspace.currentJob.status);

  const saveContract = () => void workspace.updateContract({
    title: contractForm.title,
    pov: contractForm.pov,
    targetWordsMin: contractForm.targetWordsMin,
    targetWordsMax: contractForm.targetWordsMax,
    pace: contractForm.pace,
    requiredCharacters: lines(contractForm.requiredCharacters),
    requiredForeshadows: lines(contractForm.requiredForeshadows),
    requiredHooks: lines(contractForm.requiredHooks),
    completionConditions: lines(contractForm.completionConditions),
  } as Partial<ChapterContract>);

  const onSelection = (element: HTMLTextAreaElement) => {
    const selected = element.value.slice(element.selectionStart, element.selectionEnd).trim();
    setSelectionRange(selected ? { start: element.selectionStart, end: element.selectionEnd } : null);
    setAgentContext([`第${workspace.chapterNumber}章`, workspace.currentDraft ? `正文 v${workspace.currentDraft.versionNumber}` : "正文"], selected);
  };

  const applyAgentSuggestion = () => {
    if (!selectionRange || !streamPreview) return;
    setDraftText((current) => `${current.slice(0, selectionRange.start)}${streamPreview.trim()}${current.slice(selectionRange.end)}`);
    setEditReason("接受右侧故事 Agent 对当前选区的修订建议");
    setSelectionRange(null);
    setAgentContext([`第${workspace.chapterNumber}章`, workspace.currentDraft ? `正文 v${workspace.currentDraft.versionNumber}` : "正文"]);
  };

  return (
    <div className="chapter-workbench">
      <header className="workbench-heading">
        <div><span className="workbench-kicker"><Sparkle size={15} />CHAPTER FORGE</span><h1>章节写作工作台</h1><p>契约锁定、最小上下文、候选正文和质量门在同一条可恢复流水线上。</p></div>
        <div className="workbench-state"><span className={workspace.commits.some((item) => item.isCurrent) ? "state-ok" : "state-warn"}>{workspace.commits.some((item) => item.isCurrent) ? <CheckCircle /> : <Timer />}{workspace.commits.some((item) => item.isCurrent) ? "当前章已正式提交" : "候选状态未影响正式故事"}</span></div>
      </header>

      <section className="chapter-rail" aria-label="章节状态轨道">
        <button className="rail-shift" onClick={() => workspace.selectChapter(Math.max(1, workspace.chapterNumber - 1), null)}>‹</button>
        {chapterNumbers.map((number) => {
          const contract = workspace.allContracts.find((item) => item.chapterNumber === number && item.status !== "superseded");
          const job = workspace.allJobs.find((item) => item.contract?.chapterNumber === number);
          const committed = number === workspace.chapterNumber && workspace.commits.some((item) => item.isCurrent);
          const state = committed ? "committed" : job?.status ?? contract?.status ?? "empty";
          return <button key={number} onClick={() => workspace.selectChapter(number, null)} className={`chapter-cell state-${state}${number === workspace.chapterNumber ? " is-current" : ""}`}><small>CH.</small><strong>{String(number).padStart(2, "0")}</strong><i /> <span>{committed ? "已提交" : job ? statusLabels[job.status] : contract ? contract.status === "locked" ? "契约锁定" : "契约草稿" : "未规划"}</span></button>;
        })}
        <button className="rail-shift" onClick={() => workspace.selectChapter(Math.min(workspace.project?.totalChapters ?? 100, workspace.chapterNumber + 1), null)}>›</button>
      </section>

      <div className="workbench-grid">
        <section className="forge-panel contract-panel">
          <header><div><Target size={18} /><strong>第 {workspace.chapterNumber} 章契约</strong></div><span className={`panel-badge badge-${workspace.currentContract?.status ?? "empty"}`}>{workspace.currentContract?.status === "locked" ? "LOCKED" : workspace.currentContract ? "DRAFT" : "EMPTY"}</span></header>
          {!workspace.currentContract ? <div className="empty-forge"><LockKey size={32} /><p>尚未生成本章边界。系统会从当前规划窗口推导最小推进目标。</p><button className="gold-action" onClick={() => void workspace.deriveContract()} disabled={workspace.isBusy}><Sparkle />生成章节契约</button></div> : <div className="contract-form">
            <label><span>章节标题</span><input value={contractForm.title} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, title: e.target.value })} /></label>
            <div className="contract-row"><label><span>视角</span><input value={contractForm.pov} disabled={workspace.currentContract.status !== "draft"} placeholder="第三人称限知" onChange={(e) => setContractForm({ ...contractForm, pov: e.target.value })} /></label><label><span>节奏</span><select value={contractForm.pace} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, pace: e.target.value })}><option value="slow">克制铺垫</option><option value="smooth">平稳推进</option><option value="fast">高压推进</option></select></label></div>
            <div className="contract-row"><label><span>最少字数</span><input type="number" value={contractForm.targetWordsMin} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, targetWordsMin: Number(e.target.value) })} /></label><label><span>最多字数</span><input type="number" value={contractForm.targetWordsMax} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, targetWordsMax: Number(e.target.value) })} /></label></div>
            <label><span>必须出场人物</span><textarea value={contractForm.requiredCharacters} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, requiredCharacters: e.target.value })} /></label>
            <label><span>伏笔 / 钩子</span><textarea value={[contractForm.requiredForeshadows, contractForm.requiredHooks].filter(Boolean).join("\n")} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, requiredForeshadows: e.target.value })} /></label>
            <label><span>完成条件</span><textarea value={contractForm.completionConditions} disabled={workspace.currentContract.status !== "draft"} onChange={(e) => setContractForm({ ...contractForm, completionConditions: e.target.value })} /></label>
            <div className="boundary-cards"><article><CheckCircle /><div><strong>允许推进</strong><p>{JSON.stringify(workspace.currentContract.allowedScope)}</p></div></article><article className="forbidden"><Prohibit /><div><strong>禁止提前完成</strong><p>{JSON.stringify(workspace.currentContract.forbiddenScope)}</p></div></article></div>
            {workspace.currentContract.status === "draft" && <div className="panel-actions"><button onClick={saveContract}><FloppyDisk />保存草稿</button><button className="gold-action" onClick={() => void workspace.lockContract()}><LockKey />校验并锁定</button></div>}
          </div>}
        </section>

        <section className="forge-panel manuscript-panel">
          <header><div><FileText size={18} /><strong>候选正文</strong></div><div className="version-tabs">{workspace.drafts.slice().sort((a,b) => b.versionNumber-a.versionNumber).map((draft) => <button key={draft.id} className={draft.isCurrent ? "is-active" : ""} onClick={() => !draft.isCurrent && void workspace.activateDraft(draft)}>v{draft.versionNumber}<small>{draft.kind}</small></button>)}</div></header>
          {!workspace.currentDraft ? <div className="empty-manuscript"><BookOpenText size={42} /><h3>正文尚未生成</h3><p>先锁定契约，再创建任务。生成内容只会进入候选区。</p>{workspace.currentContract?.status === "locked" && !workspace.currentJob && <button className="gold-action" onClick={() => void workspace.createJob()}><MagicWand />创建写作任务</button>}{workspace.currentJob?.status === "queued" && <button className="gold-action" onClick={() => void workspace.runJob(authorNote)}><Play />开始生成本章</button>}</div> : <>
            <div className="manuscript-meta"><span>{workspace.currentDraft.wordCount} 字</span><span>v{workspace.currentDraft.versionNumber} · {workspace.currentDraft.kind}</span><span className={dirty ? "dirty" : "saved"}>{dirty ? "有未保存修改" : "已写入候选库"}</span></div>
            <textarea className="manuscript-editor" value={draftText} onChange={(e) => setDraftText(e.target.value)} onSelect={(e) => onSelection(e.currentTarget)} spellCheck={false} />
            <div className="editor-command"><input value={editReason} onChange={(e) => setEditReason(e.target.value)} placeholder="说明本次人工修改原因（将进入审计）" />{selectionRange && streamPreview && <button className="agent-apply-button" onClick={applyAgentSuggestion}><Sparkle />应用 Agent 建议</button>}<button onClick={() => void workspace.saveManualDraft(draftText, editReason)} disabled={!dirty || workspace.currentJob?.status !== "human_review" || workspace.isBusy}><FloppyDisk />保存为新版本</button></div>
            {previousDraft && <details className="version-diff"><summary><GitDiff />与 v{previousDraft.versionNumber} 对比</summary><div><article><span>旧版 v{previousDraft.versionNumber}</span><p>{previousDraft.contentMarkdown.slice(0, 360)}</p></article><article><span>当前 v{workspace.currentDraft.versionNumber}</span><p>{workspace.currentDraft.contentMarkdown.slice(0, 360)}</p></article></div></details>}
          </>}
        </section>

        <aside className="forge-panel pipeline-panel">
          <header><div><CircleNotch size={18} /><strong>生产流水线</strong></div>{workspace.currentJob && <span className={`panel-badge job-${workspace.currentJob.status}`}>{statusLabels[workspace.currentJob.status]}</span>}</header>
          <div className="pipeline-steps">{["契约锁定","编译上下文","生成正文","事实抽取","硬规则校验","三角色复核","人工确认","正式提交"].map((label, index) => <div key={label} className={index <= (workspace.currentJob ? Math.min(7, ["queued","compiling_context","drafting","extracting","validating","reviewing","human_review","completed"].indexOf(workspace.currentJob.status)) : -1) ? "is-done" : ""}><i>{index + 1}</i><span>{label}</span></div>)}</div>
          {workspace.currentJob ? <div className="job-diagnostics"><dl><div><dt>尝试次数</dt><dd>{workspace.currentJob.attemptNumber}</dd></div><div><dt>自动修订</dt><dd>{workspace.currentJob.currentRevisionRound}/2</dd></div><div><dt>Revision</dt><dd>{workspace.currentJob.revision}</dd></div></dl>{workspace.currentJob.errorCode && <p className="pipeline-error"><WarningCircle />{workspace.currentJob.errorCode}</p>}</div> : <p className="muted-copy">锁定契约后才能创建可恢复任务。</p>}
          <label className="author-note"><span>本次作者补充</span><textarea value={authorNote} onChange={(e) => setAuthorNote(e.target.value)} placeholder="只对本次生成生效，不改变 Canon" /></label>
          <div className="pipeline-actions">
            {workspace.currentContract?.status === "locked" && !workspace.currentJob && <button className="gold-action" onClick={() => void workspace.createJob()}><MagicWand />创建任务</button>}
            {workspace.currentJob?.status === "queued" && <button className="gold-action" onClick={() => void workspace.runJob(authorNote)}><Play />运行流水线</button>}
            {active && <button className="danger-action" onClick={() => void workspace.cancelJob()}><Stop />停止任务</button>}
            {workspace.currentJob && ["failed","interrupted","cancelled"].includes(workspace.currentJob.status) && <button onClick={() => void workspace.retryJob()}><ArrowClockwise />恢复任务</button>}
          </div>
          <section className="context-trace"><header><strong>上下文追踪</strong><span>{workspace.trace ? `${workspace.trace.items.length} 条 / ${workspace.trace.tokenBudget} Token` : "等待编译"}</span></header>{workspace.trace?.items.slice(0, 6).map((item) => <article key={item.id}><i /><div><strong>{item.title}</strong><p>{item.reason}</p></div><span>{item.tokenEstimate}</span></article>) ?? <p className="muted-copy">运行后显示 Canon、状态和历史证据来源。</p>}</section>
        </aside>
      </div>
    </div>
  );
}
