import { useQuery } from "@tanstack/react-query";
import { CheckCircle, CircleNotch, ShieldWarning, XCircle } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { TrialReadiness, TrialRunSize } from "../types";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";

export function useTrialReadiness(chapterCount: TrialRunSize) {
  const { project } = useStoryWorkspace();
  return useQuery({
    queryKey: ["trial-readiness", project?.id, chapterCount],
    queryFn: () => api.trialReadiness(project!.id, chapterCount),
    enabled: Boolean(project),
    refetchInterval: 10_000,
  });
}

export function TrialReadinessPanel({ chapterCount = 1, data, compact = false }: {
  chapterCount?: TrialRunSize;
  data?: TrialReadiness;
  compact?: boolean;
}) {
  const navigate = useNavigate();
  const query = useTrialReadiness(chapterCount);
  const readiness = data ?? query.data;

  return <section className={`trial-readiness${compact ? " is-compact" : ""}`} aria-label="试写就绪检查">
    <header>
      <div><ShieldWarning size={18} /><strong>试写就绪检查</strong></div>
      {readiness && <span className={readiness.ready ? "readiness-ready" : "readiness-blocked"}>{readiness.ready ? "READY" : "BLOCKED"}</span>}
    </header>
    {!readiness ? <div className="readiness-loading"><CircleNotch className="spin" />正在核对模型、Canon 与章节边界…</div> : <>
      <div className="readiness-range"><span>本批次</span><strong>第 {readiness.startChapter}—{readiness.endChapter} 章</strong><small>最多安全连续 {readiness.maxSafeChapterCount} 章</small></div>
      <div className="readiness-checks">{readiness.checks.map((check) => <button key={check.code} className={`readiness-check check-${check.status}`} onClick={() => check.actionPath && navigate(check.actionPath)} disabled={!check.actionPath}>
        {check.status === "ready" ? <CheckCircle weight="fill" /> : check.status === "warning" ? <ShieldWarning weight="fill" /> : <XCircle weight="fill" />}
        <div><strong>{check.title}</strong><span>{check.detail}</span></div>
      </button>)}</div>
    </>}
  </section>;
}
