import { useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise, CheckCircle, MagnifyingGlass, Flag, GitDiff, Info, MagicWand,
  ShieldCheck, ShieldWarning, Sparkle, WarningCircle, XCircle,
} from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { useChapterWorkspace } from "../hooks/useChapterWorkspace";
import { useStoryStore } from "../store/useStoryStore";
import type { QualityFinding } from "../types";

const reviewerLabels: Record<string, string> = {
  deterministic: "确定性规则",
  continuity_reviewer: "连续性审稿",
  story_editor: "故事编辑",
  style_reviewer: "文风审稿",
};

export function QualityCenterPage() {
  const workspace = useChapterWorkspace();
  const navigate = useNavigate();
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const [severity, setSeverity] = useState("all");
  const [selectedFindingId, setSelectedFindingId] = useState<string | null>(null);
  const [riskReason, setRiskReason] = useState("");
  const [revisionReason, setRevisionReason] = useState("");

  const findings = useMemo(() => (workspace.quality?.findings ?? []).filter((item) => severity === "all" || item.severity === severity), [workspace.quality, severity]);
  const selectedFinding = findings.find((item) => item.id === selectedFindingId) ?? findings[0] ?? null;
  const blocking = workspace.quality?.openBlockingCount ?? 0;
  const currentCommit = workspace.commits.find((item) => item.isCurrent);

  useEffect(() => {
    setAgentContext([`第${workspace.chapterNumber}章`, "质量中心", selectedFinding ? selectedFinding.ruleCode : "质量总览"], selectedFinding?.message ?? "");
    return () => setAgentContext([]);
  }, [workspace.chapterNumber, selectedFinding?.id, setAgentContext]);

  const runSummary = (role: string) => {
    const run = workspace.quality?.runs.find((item) => (item.gateType === "deterministic" ? "deterministic" : item.reviewerRole) === role && item.chapterDraftId === workspace.quality?.currentDraftId);
    const count = run?.findings.filter((item) => item.status === "open").length ?? 0;
    return { run, count };
  };

  const approveAndCommit = async (mode: "manual" | "guarded_auto") => {
    if (mode === "manual" && !window.confirm("人工批准会写入正式故事状态。确认当前问题已由你判断可接受？")) return;
    await workspace.approveAndCommit(mode);
  };

  return (
    <div className="quality-center">
      <header className="quality-heading">
        <div><span className="workbench-kicker"><ShieldCheck size={15} />QUALITY GATE</span><h1>章节质量中心</h1><p>每一条结论都必须能追溯到规则、原文证据和模型运行。</p></div>
        <div className="chapter-quality-picker"><span>当前章节</span><input aria-label="质量中心章节号" type="number" min={1} max={workspace.project?.totalChapters ?? 1} value={workspace.chapterNumber} onChange={(e) => workspace.selectChapter(Math.max(1, Math.min(workspace.project?.totalChapters ?? 1, Number(e.target.value))), null)} /><button onClick={() => navigate("/writing")}>查看正文</button></div>
      </header>

      <section className="quality-overview">
        <article className={blocking ? "overview-blocked" : "overview-pass"}><div>{blocking ? <XCircle /> : <CheckCircle />}</div><span>综合质量门</span><strong>{currentCommit ? "已正式提交" : blocking ? "阻断" : workspace.quality ? "可批准" : "等待运行"}</strong><small>{blocking ? `${blocking} 个严重问题尚未处理` : currentCommit ? `提交于 ${new Date(currentCommit.committedAt).toLocaleString("zh-CN")}` : "候选稿尚未影响正式状态"}</small></article>
        {["deterministic", "continuity_reviewer", "story_editor", "style_reviewer"].map((role) => {
          const summary = runSummary(role); return <article key={role} className={summary.run?.status === "succeeded" && !summary.count ? "gate-pass" : summary.run ? "gate-warn" : "gate-idle"}><span>{reviewerLabels[role]}</span><strong>{summary.run ? summary.run.status === "succeeded" ? summary.count ? `${summary.count} 项` : "通过" : summary.run.status : "未运行"}</strong><small>{summary.run?.modelRunId ? `运行 ${summary.run.modelRunId.slice(0, 8)}` : "等待当前正文"}</small></article>;
        })}
      </section>

      <div className="quality-layout">
        <section className="quality-findings-panel">
          <header><div><MagnifyingGlass /><strong>问题与证据</strong><span>{findings.length}</span></div><div className="severity-filter">{["all","blocker","error","warning","info"].map((value) => <button key={value} className={severity === value ? "is-active" : ""} onClick={() => setSeverity(value)}>{value === "all" ? "全部" : value}</button>)}</div></header>
          <div className="finding-list">{findings.length ? findings.map((finding) => <button key={finding.id} className={`finding-row severity-${finding.severity}${selectedFinding?.id === finding.id ? " is-selected" : ""}`} onClick={() => setSelectedFindingId(finding.id)}><span className="finding-icon">{finding.severity === "blocker" || finding.severity === "error" ? <WarningCircle /> : finding.severity === "warning" ? <ShieldWarning /> : <Info />}</span><div><header><strong>{finding.ruleCode}</strong><span>{finding.status}</span></header><p>{finding.message}</p><small>{finding.category} · {finding.suggestedFix || "等待人工判断"}</small></div></button>) : <div className="empty-quality"><CheckCircle /><h3>当前没有质量问题</h3><p>质量运行完成后，问题会按证据与严重度集中在这里。</p></div>}</div>
        </section>

        <aside className="quality-detail-panel">
          {selectedFinding ? <>
            <header><span className={`severity-chip severity-${selectedFinding.severity}`}>{selectedFinding.severity}</span><strong>{selectedFinding.ruleCode}</strong></header>
            <h2>{selectedFinding.message}</h2>
            <section><span>定位与证据</span><pre>{JSON.stringify({ location: selectedFinding.location, evidence: selectedFinding.evidence }, null, 2)}</pre></section>
            <section><span>建议修复</span><p>{selectedFinding.suggestedFix || "结合章节契约与当前正式状态进行最小范围修订。"}</p></section>
            {selectedFinding.status === "open" && !["blocker","error"].includes(selectedFinding.severity) && <section className="risk-box"><span>接受风险</span><textarea value={riskReason} onChange={(e) => setRiskReason(e.target.value)} placeholder="必须填写判断依据" /><button disabled={!riskReason.trim()} onClick={() => void workspace.acceptRisk(selectedFinding.id, riskReason)}><Flag />记录并接受</button></section>}
            {["blocker","error"].includes(selectedFinding.severity) && <div className="blocking-note"><ShieldWarning />严重问题不能通过“接受风险”绕过自动质量门。</div>}
          </> : <div className="quality-placeholder"><GitDiff size={36} /><p>选择一个问题查看原文证据、规则来源和修复建议。</p></div>}
        </aside>
      </div>

      <footer className="quality-actionbar">
        <div><span>当前候选</span><strong>{workspace.currentDraft ? `v${workspace.currentDraft.versionNumber} · ${workspace.currentDraft.wordCount} 字` : "无"}</strong><small>自动修订 {workspace.currentJob?.currentRevisionRound ?? 0}/2</small></div>
        <input value={revisionReason} onChange={(e) => setRevisionReason(e.target.value)} placeholder="补充本轮修订重点" />
        <button onClick={() => void workspace.reviseJob(revisionReason)} disabled={workspace.currentJob?.status !== "human_review" || workspace.isBusy}><MagicWand />按问题自动修订</button>
        <button onClick={() => void approveAndCommit("manual")} disabled={workspace.currentJob?.status !== "human_review" || workspace.isBusy}><ShieldWarning />人工批准</button>
        <button className="gold-action" onClick={() => void approveAndCommit("guarded_auto")} disabled={workspace.currentJob?.status !== "human_review" || blocking > 0 || workspace.isBusy}><Sparkle />质量通过并提交</button>
        {workspace.currentJob && ["failed","interrupted","cancelled"].includes(workspace.currentJob.status) && <button onClick={() => void workspace.retryJob()}><ArrowClockwise />恢复任务</button>}
      </footer>
    </div>
  );
}
