import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowClockwise, CalendarCheck, CheckCircle, CircleNotch, Clock, Coins, Gauge,
  Lightning, ListChecks, Pause, Play, ShieldWarning, Stop, Timer, WarningCircle,
} from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiClientError } from "../api/client";
import { TrialReadinessPanel, useTrialReadiness } from "../components/TrialReadinessPanel";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { useStoryStore } from "../store/useStoryStore";
import type { AutomationPolicy, AutomationRun, TrialRunSize } from "../types";

const runLabels: Record<string, string> = {
  queued: "排队中", running: "运行中", completed: "已完成", partial: "部分完成", blocked: "已阻断",
  failed: "失败", cancelled: "已取消", cancel_requested: "停止中", interrupted: "已中断", missed: "已错过",
};
const itemLabels: Record<string, string> = {
  waiting: "等待", running: "生成中", committed: "已提交", isolated: "已隔离", failed: "失败",
  skipped: "已跳过", cancelled: "已取消",
};
const activeRunStatuses = new Set(["queued", "running", "cancel_requested"]);

function errorText(error: unknown) {
  if (error instanceof ApiClientError) {
    const map: Record<string, string> = {
      AUTOMATION_LEASE_LOST: "托管租约已经转移，请刷新后按最新状态恢复。",
      AUTOMATION_COST_LIMIT_REACHED: "预计费用将超过每日上限，本批次已安全停止。",
      AUTOMATION_MODEL_PRICE_REQUIRED: "费用保护已开启，但相关模型尚未填写输入/输出价格。",
      AUTOMATION_RUN_NOT_RESUMABLE: "该运行当前不能恢复，请查看可用操作。",
      AUTOMATION_RUN_CANCELLED: "运行已收到停止请求。",
    };
    return map[error.payload.code] ?? `${error.payload.code}：${error.payload.message}`;
  }
  return error instanceof Error ? error.message : "自动托管操作失败。";
}

function PolicyEditor({ policy, saving, onSave }: { policy: AutomationPolicy; saving: boolean; onSave: (value: AutomationPolicy) => void }) {
  const [form, setForm] = useState(policy);
  useEffect(() => setForm(policy), [policy.revision]);
  const changed = JSON.stringify(form) !== JSON.stringify(policy);
  return <section className="automation-policy-card">
    <header><div><Timer /><strong>每日托管策略</strong></div><label className="switch-row"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} /><i /><span>{form.enabled ? "已启用" : "已关闭"}</span></label></header>
    <div className="automation-policy-grid">
      <label><span>运行时间</span><input type="time" value={form.timeOfDay} onChange={(event) => setForm({ ...form, timeOfDay: event.target.value })} /></label>
      <label><span>时区</span><select value={form.timezone} onChange={(event) => setForm({ ...form, timezone: event.target.value })}><option value="Asia/Shanghai">Asia/Shanghai</option><option value="UTC">UTC</option><option value="Asia/Tokyo">Asia/Tokyo</option></select></label>
      <label><span>每批章节</span><select value={form.chaptersPerRun} onChange={(event) => setForm({ ...form, chaptersPerRun: Number(event.target.value) })}>{[1,2,3,4,5].map((value) => <option key={value} value={value}>{value} 章</option>)}</select></label>
      <label><span>修订上限</span><select value={form.maxRevisionRounds} onChange={(event) => setForm({ ...form, maxRevisionRounds: Number(event.target.value) })}><option value={0}>不自动修订</option><option value={1}>1 轮</option><option value={2}>2 轮</option></select></label>
      <label><span>最少字数</span><input type="number" min={1} value={form.targetWordsMin} onChange={(event) => setForm({ ...form, targetWordsMin: Number(event.target.value) })} /></label>
      <label><span>最多字数</span><input type="number" min={1} value={form.targetWordsMax} onChange={(event) => setForm({ ...form, targetWordsMax: Number(event.target.value) })} /></label>
      <label><span>每日费用上限</span><input type="number" min={0} step={0.01} value={form.dailyCostLimit ?? ""} placeholder="不限制" onChange={(event) => setForm({ ...form, dailyCostLimit: event.target.value === "" ? null : Number(event.target.value) })} /></label>
      <label><span>停止策略</span><select value={form.stopPolicy} onChange={(event) => setForm({ ...form, stopPolicy: event.target.value as AutomationPolicy["stopPolicy"] })}><option value="stop_on_blocking">仅阻断问题停止</option><option value="stop_on_any_failure">任意失败停止</option></select></label>
    </div>
    <footer><span>{form.enabled ? `下次运行：${form.nextRunAt ? new Date(form.nextRunAt).toLocaleString("zh-CN") : "保存后计算"}` : "手动试写不会自动开启每日托管"}</span><button className="gold-action" disabled={!changed || saving || form.targetWordsMin > form.targetWordsMax} onClick={() => onSave(form)}>保存策略</button></footer>
  </section>;
}

export function AutomationPage() {
  const { project } = useStoryWorkspace();
  const client = useQueryClient();
  const navigate = useNavigate();
  const setNotice = useStoryStore((state) => state.setNotice);
  const setAgentContext = useStoryStore((state) => state.setAgentContext);
  const selectChapter = useStoryStore((state) => state.selectChapter);
  const [trialSize, setTrialSize] = useState<TrialRunSize>(1);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const readinessQuery = useTrialReadiness(trialSize);
  const policyQuery = useQuery({ queryKey: ["automation-policy", project?.id], queryFn: () => api.automationPolicy(project!.id), enabled: Boolean(project) });
  const runsQuery = useQuery({
    queryKey: ["automation-runs", project?.id], queryFn: () => api.automationRuns(project!.id), enabled: Boolean(project),
    refetchInterval: (query) => ((query.state.data as AutomationRun[] | undefined)?.some((run) => activeRunStatuses.has(run.status)) ? 1200 : 8000),
  });
  const reportsQuery = useQuery({ queryKey: ["automation-reports", project?.id], queryFn: () => api.automationReports(project!.id), enabled: Boolean(project), refetchInterval: 10_000 });
  const runs = runsQuery.data ?? [];
  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? runs[0] ?? null;
  const activeRun = runs.find((run) => activeRunStatuses.has(run.status));

  useEffect(() => { if (runs[0] && !selectedRunId) setSelectedRunId(runs[0].id); }, [runs[0]?.id, selectedRunId]);
  useEffect(() => {
    setAgentContext(["自动托管", selectedRun ? `批次 ${selectedRun.id.slice(0, 8)}` : "尚无运行", `${trialSize} 章试写`]);
    return () => setAgentContext([]);
  }, [selectedRun?.id, trialSize, setAgentContext]);

  const refresh = async () => {
    if (!project) return;
    await Promise.all([
      client.invalidateQueries({ queryKey: ["automation-policy", project.id] }),
      client.invalidateQueries({ queryKey: ["automation-runs", project.id] }),
      client.invalidateQueries({ queryKey: ["automation-reports", project.id] }),
      client.invalidateQueries({ queryKey: ["trial-readiness", project.id] }),
      client.invalidateQueries({ queryKey: ["projects"] }),
    ]);
  };
  const action = useMutation({
    mutationFn: async ({ run, success }: { run: () => Promise<unknown>; success: string }) => { const result = await run(); return { result, success }; },
    onSuccess: async ({ result, success }) => {
      setError(null); setNotice(success);
      if (result && typeof result === "object" && "id" in result) setSelectedRunId(String((result as { id: string }).id));
      await refresh();
    },
    onError: (cause) => { setError(errorText(cause)); void refresh(); },
  });

  const startTrial = () => {
    if (!project || !readinessQuery.data?.ready || activeRun) return;
    const warnings = readinessQuery.data.checks.filter((item) => item.status === "warning");
    if (warnings.length && !window.confirm(`存在 ${warnings.length} 条提醒，仍要开始本次试写吗？`)) return;
    action.mutate({
      run: () => api.createAutomationRun(project.id, trialSize, `trial:${trialSize}:${crypto.randomUUID()}`),
      success: `${trialSize} 章试写批次已创建，定时托管保持原状态。`,
    });
  };
  const savePolicy = (policy: AutomationPolicy) => {
    if (!project || !policyQuery.data) return;
    action.mutate({
      run: () => api.updateAutomationPolicy(project.id, {
        expectedRevision: policyQuery.data.revision, enabled: policy.enabled, timeOfDay: policy.timeOfDay,
        timezone: policy.timezone, chaptersPerRun: policy.chaptersPerRun, targetWordsMin: policy.targetWordsMin,
        targetWordsMax: policy.targetWordsMax, maxRevisionRounds: policy.maxRevisionRounds,
        dailyCostLimit: policy.dailyCostLimit, stopPolicy: policy.stopPolicy, approvalMode: policy.approvalMode,
      }),
      success: policy.enabled ? "每日自动托管策略已启用。" : "托管策略已保存，定时运行保持关闭。",
    });
  };
  const runCommand = (command: "cancel" | "resume" | "catch_up") => {
    if (!project || !selectedRun) return;
    const methods = { cancel: api.cancelAutomationRun, resume: api.resumeAutomationRun, catch_up: api.catchUpAutomationRun };
    action.mutate({ run: () => methods[command](project.id, selectedRun.id), success: command === "cancel" ? "已发送停止请求。" : command === "resume" ? "运行已进入恢复队列。" : "补跑任务已创建。" });
  };
  const openChapter = (chapter: number, jobId: string | null, quality = false) => { selectChapter(chapter, jobId); navigate(quality ? "/quality" : "/writing"); };

  const currentReport = reportsQuery.data?.[0];
  const completionPercent = selectedRun?.plannedCount ? Math.round((selectedRun.succeededCount / selectedRun.plannedCount) * 100) : 0;

  if (!project) return <div className="connection-state"><strong>请先选择作品</strong></div>;
  return <div className="automation-page">
    <header className="automation-heading"><div><span className="workbench-kicker"><Lightning /> AUTONOMOUS DESK</span><h1>自动托管控制台</h1><p>先小批量验证，再逐步扩大；所有运行都可诊断、可停止、可恢复。</p></div><div className={`automation-live ${activeRun ? "is-running" : ""}`}>{activeRun ? <CircleNotch className="spin" /> : <CheckCircle />}<div><strong>{activeRun ? "托管运行中" : "队列空闲"}</strong><span>{activeRun ? `第 ${activeRun.startChapter ?? "—"}—${activeRun.endChapter ?? "—"} 章` : policyQuery.data?.enabled ? "等待下一次定时运行" : "每日托管未启用"}</span></div></div></header>

    <section className="trial-launcher"><header><div><Play /><strong>分阶段试写</strong></div><span>手动试写不会改变每日定时开关</span></header><div className="trial-size-picker">{([1,3,5] as TrialRunSize[]).map((size) => <button key={size} className={trialSize === size ? "is-active" : ""} onClick={() => setTrialSize(size)}><small>{size === 1 ? "冒烟测试" : size === 3 ? "短链路" : "连续验证"}</small><strong>{size} 章</strong><span>{size === 1 ? "逐步确认界面与模型" : size === 3 ? "观察跨章状态更新" : "检查节奏与恢复能力"}</span></button>)}</div><div className="trial-launch-actions"><span>{readinessQuery.data?.ready ? <><CheckCircle />本批次已就绪</> : <><ShieldWarning />请先处理阻断项</>}</span><button className="gold-action" disabled={!readinessQuery.data?.ready || Boolean(activeRun) || action.isPending} onClick={startTrial}><Lightning />开始第 {readinessQuery.data?.startChapter ?? "—"}—{readinessQuery.data?.endChapter ?? "—"} 章</button></div></section>

    <div className="automation-grid">
      <main className="automation-main">
        {policyQuery.data && <PolicyEditor policy={policyQuery.data} saving={action.isPending} onSave={savePolicy} />}
        <section className="run-console"><header><div><ListChecks /><strong>运行队列</strong></div><span>{runs.length} 个批次</span></header><div className="run-console-body"><aside className="run-list">{runs.map((run) => <button key={run.id} className={selectedRun?.id === run.id ? "is-selected" : ""} onClick={() => setSelectedRunId(run.id)}><i className={`run-dot run-${run.status}`} /><div><strong>{run.trigger === "manual" ? `试写 ${(run.requestedChapterCount ?? run.plannedCount) || "—"} 章` : run.trigger === "scheduled" ? "每日托管" : "补跑批次"}</strong><span>{new Date(run.createdAt).toLocaleString("zh-CN")}</span></div><em>{runLabels[run.status] ?? run.status}</em></button>)}{!runs.length && <div className="automation-empty">尚无运行。先完成左侧就绪检查，再启动一章试写。</div>}</aside><div className="run-detail">{selectedRun ? <>
          <header><div><strong>{runLabels[selectedRun.status] ?? selectedRun.status}</strong><span>批次 {selectedRun.id.slice(0, 8)} · REV {selectedRun.revision}</span></div><div className="run-actions">{selectedRun.availableActions.includes("cancel") && <button onClick={() => runCommand("cancel")}><Stop />停止</button>}{selectedRun.availableActions.includes("resume") && <button onClick={() => runCommand("resume")}><ArrowClockwise />恢复</button>}{selectedRun.availableActions.includes("catch_up") && <button onClick={() => runCommand("catch_up")}><CalendarCheck />补跑</button>}</div></header>
          <div className="run-progress"><div><span style={{ width: `${completionPercent}%` }} /></div><strong>{completionPercent}%</strong><small>{selectedRun.succeededCount}/{selectedRun.plannedCount} 章正式提交</small></div>
          <div className="run-metrics"><article><Gauge /><span>Token</span><strong>{selectedRun.totalTokens.toLocaleString()}</strong></article><article><Coins /><span>预计费用（配置币种）</span><strong>{selectedRun.estimatedCost.toFixed(4)}</strong></article><article><ShieldWarning /><span>隔离</span><strong>{selectedRun.isolatedCount}</strong></article><article><Clock /><span>运行范围</span><strong>{selectedRun.startChapter ?? "—"}—{selectedRun.endChapter ?? "—"}</strong></article></div>
          <div className="run-items">{selectedRun.items.map((item) => <article key={item.id} className={`run-item item-${item.status}`}><i>{item.sequenceNumber}</i><div><strong>第 {item.chapterNumber} 章</strong><span>{itemLabels[item.status] ?? item.status}{item.errorCode ? ` · ${item.errorCode}` : ""}</span></div><small>{item.totalTokens.toLocaleString()} Token · {item.estimatedCost.toFixed(4)}</small><div><button onClick={() => openChapter(item.chapterNumber, item.chapterJobId)}>正文</button>{item.chapterJobId && <button onClick={() => openChapter(item.chapterNumber, item.chapterJobId, true)}>质量</button>}</div></article>)}</div>
          {(selectedRun.stopReason || selectedRun.diagnostic) && <div className="run-diagnostic"><WarningCircle /><div><strong>{selectedRun.stopReason ?? "运行诊断"}</strong><pre>{JSON.stringify(selectedRun.diagnostic, null, 2)}</pre></div></div>}
        </> : <div className="automation-empty">选择一个批次查看章节级状态、费用和恢复操作。</div>}</div></div></section>
      </main>
      <aside className="automation-side"><TrialReadinessPanel chapterCount={trialSize} data={readinessQuery.data} /><section className="daily-report-card"><header><div><CalendarCheck /><strong>今日托管报告</strong></div><span>{currentReport?.localDate ?? "暂无"}</span></header>{currentReport ? <><div className="report-score"><strong>{currentReport.succeededCount}</strong><span>章成功</span><small>{currentReport.isolatedCount} 隔离 / {currentReport.runCount} 批次</small></div><dl><div><dt>总 Token</dt><dd>{currentReport.totalTokens.toLocaleString()}</dd></div><div><dt>预计费用</dt><dd>{currentReport.estimatedCost.toFixed(4)}</dd></div><div><dt>时区</dt><dd>{currentReport.timezone}</dd></div></dl></> : <div className="automation-empty">首个试写批次结束后，这里会生成可审计日报。</div>}</section></aside>
    </div>
    {error && <div className="toast-notice error" role="alert"><WarningCircle />{error}<button onClick={() => setError(null)}><Pause /></button></div>}
  </div>;
}
