import { CheckCircle, LinkSimple, Warning } from "@phosphor-icons/react";
import { getPacingRiskCount, validateMilestones } from "../domain/planning";
import { useStoryStore } from "../store/useStoryStore";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";

export function StatusBar() {
  const { plan, isDisconnected } = useStoryWorkspace();
  const milestones = plan?.milestones ?? [];
  const validations = validateMilestones(milestones);
  const errors = validations.filter((item) => item.severity === "error").length;
  const dependencies = validations.filter((item) => item.rule === "PLAN_CONTRACT_INCOMPLETE").length;
  const pacing = getPacingRiskCount(milestones);

  return (
    <footer className="statusbar">
      <div className={`status-item ${errors ? "status-error" : "status-ok"}`}>
        <CheckCircle size={21} weight="duotone" />
        <span>规划约束通过</span><strong>{errors ? `${12 - errors}/12` : "12/12"}</strong>
      </div>
      <div className="status-item status-warning">
        <Warning size={21} weight="duotone" /><span>节奏风险</span><strong>{pacing}</strong>
      </div>
      <div className="status-item status-neutral">
        <LinkSimple size={20} /><span>未解决依赖</span><strong>{dependencies}</strong>
      </div>
      <span className="statusbar-fill" />
      <span className="local-note">{isDisconnected ? "本地数据服务已断开" : "SQLite 已连接 · 所有正式修改可审计"}</span>
    </footer>
  );
}
