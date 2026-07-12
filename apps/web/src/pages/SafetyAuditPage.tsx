import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, DownloadSimple, Pulse, UploadSimple, WarningCircle } from "@phosphor-icons/react";
import { ChangeEvent, useMemo, useState } from "react";
import { api } from "../api/client";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import type { AuditEvent, ModelRun } from "../types";

function formatDate(value: string | null | undefined): string {
  if (!value) return "未结束";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function diagnosticSummary(run: ModelRun): string {
  const diagnostic = run.diagnostic ?? {};
  const reason = typeof diagnostic.reason === "string" ? diagnostic.reason : run.errorCode;
  const attempts = typeof diagnostic.attempts === "number" ? ` · ${diagnostic.attempts} 次尝试` : "";
  const request = run.requestId ? ` · 请求 ${run.requestId.slice(0, 8)}` : "";
  return [run.status, reason, attempts, request].filter(Boolean).join("");
}

function eventLabel(event: AuditEvent): string {
  const payload = event.payload;
  if (event.eventType === "proposal.generation_failed") return `结构化提案失败：${String(payload.code ?? "unknown")}`;
  if (event.eventType === "proposal.generated") return "结构化提案已生成";
  if (event.eventType === "proposal.applied") return "提案已应用";
  if (event.eventType === "proposal.rejected") return "提案已拒绝";
  if (event.eventType === "event.undone") return "审计事件已撤销";
  return event.eventType;
}

export function SafetyAuditPage() {
  const { project, audits, modelRuns, createBackup, selectProject, projects } = useStoryWorkspace();
  const [eventFilter, setEventFilter] = useState("");
  const [runFilter, setRunFilter] = useState("");
  const queryClient = useQueryClient();

  const backupsQuery = useQuery({
    queryKey: ["backups", project?.id],
    queryFn: () => api.backups(project!.id),
    enabled: Boolean(project),
  });

  const filteredAudits = useMemo(
    () => audits.filter((item) => !eventFilter || item.eventType === eventFilter),
    [audits, eventFilter],
  );
  const filteredRuns = useMemo(
    () => modelRuns.filter((item) => !runFilter || item.status === runFilter),
    [modelRuns, runFilter],
  );
  const failedRuns = modelRuns.filter((item) => item.status !== "succeeded" && item.status !== "running").slice(0, 5);

  const restoreMutation = useMutation({
    mutationFn: api.restoreBackup,
    onSuccess: async (restored) => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      const exists = projects.some((item) => item.id === restored.id);
      if (!exists) selectProject(restored.id);
    },
  });

  const onRestore = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) restoreMutation.mutate(file);
    event.target.value = "";
  };

  if (!project) return <div className="connection-state"><strong>请先选择作品</strong></div>;

  const backups = backupsQuery.data ?? [];
  const eventTypes = Array.from(new Set(audits.map((item) => item.eventType)));
  const runStatuses = Array.from(new Set(modelRuns.map((item) => item.status)));

  return (
    <div className="safety-page">
      <header className="safety-header">
        <div>
          <span className="placeholder-kicker"><Archive size={19} />安全与审计</span>
          <h1>备份恢复与调用诊断</h1>
          <p>备份、审计事件、模型调用记录和错误诊断集中在这里，右侧 Agent 仍保持当前作品上下文。</p>
        </div>
        <div className="safety-actions">
          <button onClick={() => void createBackup()}><Archive size={17} />创建备份</button>
          <label className="upload-button"><UploadSimple size={17} />恢复上传<input type="file" accept=".zip,application/zip" onChange={onRestore} /></label>
        </div>
      </header>

      <section className="safety-grid">
        <article className="safety-panel backup-panel" aria-label="备份管理">
          <header><strong>备份管理</strong><span>{backups.length} 份</span></header>
          <div className="backup-list">
            {backups.map((backup) => (
              <div className="backup-row" key={backup.backupId}>
                <div><strong>{formatDate(backup.createdAt)}</strong><span>{backup.projectTitle} · {formatBytes(backup.sizeBytes)}</span></div>
                <span className={backup.isValid ? "status-pill ok" : "status-pill danger"}>{backup.isValid ? "校验通过" : "校验失败"}</span>
                <a href={`/api/v1/projects/${project.id}/backups/${backup.backupId}/download`}><DownloadSimple size={15} />下载</a>
              </div>
            ))}
            {!backups.length && <p className="empty-copy">还没有备份。创建后会显示校验状态、大小和来源项目。</p>}
          </div>
          {restoreMutation.isSuccess && <p className="restore-result">恢复完成，已创建新项目：{restoreMutation.data.title}</p>}
          {restoreMutation.isError && <p className="restore-error">{restoreMutation.error.message}</p>}
        </article>

        <article className="safety-panel audit-panel" aria-label="审计时间线">
          <header><strong>审计时间线</strong><select aria-label="审计事件过滤" value={eventFilter} onChange={(event) => setEventFilter(event.target.value)}><option value="">全部事件</option>{eventTypes.map((type) => <option key={type} value={type}>{type}</option>)}</select></header>
          <div className="audit-list">
            {filteredAudits.slice(0, 12).map((event) => (
              <div className="audit-row" key={event.id}>
                <i /><div><strong>{eventLabel(event)}</strong><span>{event.entityType} · {event.entityId}</span></div><time>{formatDate(event.createdAt)}</time>
              </div>
            ))}
            {!filteredAudits.length && <p className="empty-copy">当前过滤条件没有审计事件。</p>}
          </div>
        </article>

        <article className="safety-panel runs-panel" aria-label="模型调用记录">
          <header><strong>模型调用记录</strong><select aria-label="模型调用状态过滤" value={runFilter} onChange={(event) => setRunFilter(event.target.value)}><option value="">全部状态</option>{runStatuses.map((status) => <option key={status} value={status}>{status}</option>)}</select></header>
          <div className="run-table">
            {filteredRuns.slice(0, 12).map((run) => (
              <div className="run-row" key={run.id}>
                <span className={`status-pill ${run.status === "succeeded" ? "ok" : run.status === "running" ? "live" : "danger"}`}>{run.status}</span>
                <div><strong>{run.providerName || "未知 Provider"} / {run.modelId || "未知模型"}</strong><span>{run.role} · {run.totalTokens ?? 0} tokens · {run.durationMs ?? 0} ms</span></div>
                <time>{formatDate(run.startedAt)}</time>
              </div>
            ))}
            {!filteredRuns.length && <p className="empty-copy">暂无模型调用记录。</p>}
          </div>
        </article>

        <article className="safety-panel diagnostics-panel" aria-label="错误诊断">
          <header><strong>错误诊断</strong><WarningCircle size={18} /></header>
          <div className="diagnostic-list">
            {failedRuns.map((run) => (
              <div className="diagnostic-row" key={run.id}>
                <Pulse size={17} /><div><strong>{run.errorCode ?? run.status}</strong><span>{diagnosticSummary(run)}</span></div>
              </div>
            ))}
            {!failedRuns.length && <p className="empty-copy">没有失败或中断的模型调用。请求 ID 和重试次数会在失败时显示。</p>}
          </div>
        </article>
      </section>

      <footer className="safety-footer"><Pulse size={16} />备份 ZIP 不包含 API Key；模型调用记录只保存状态、Token、耗时、请求 ID 与安全诊断摘要。</footer>
    </div>
  );
}
