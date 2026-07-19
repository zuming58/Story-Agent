import { CaretDown, Clock, GearSix, NotePencil } from "@phosphor-icons/react";
import { useNavigate } from "react-router-dom";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";

export function TopBar() {
  const navigate = useNavigate();
  const { project } = useStoryWorkspace();
  if (!project) return <header className="topbar"><span className="mode-chip">正在连接本地数据服务…</span></header>;
  const progress = (project.currentChapter / project.totalChapters) * 100;

  return (
    <header className="topbar">
      <button className="project-switcher">
        <strong>{project.title}</strong>{project.projectKind === "demo" && <em className="project-kind-badge">示例项目</em>}
        <CaretDown size={15} />
      </button>
      <span className="mode-chip">长篇网文</span>
      <div className="topbar-spacer" />
      <div className="chapter-progress" aria-label={`当前第 ${project.currentChapter} 章，共 ${project.totalChapters} 章`}>
        <span>第 {project.currentChapter} / {project.totalChapters} 章</span>
        <span className="progress-track"><span style={{ width: `${Math.max(progress, 5)}%` }} /></span>
      </div>
      <span className="topbar-divider" />
      <div className="model-status">
        <span>{project.model ?? "模拟 Agent"} · 在线</span>
        <i aria-label="模型在线" />
      </div>
      <span className="topbar-divider" />
      <div className="automation-status"><Clock size={17} /><span>{project.automationSchedule ?? "自动托管未启用"}</span></div>
      <button className="icon-button" aria-label="工作记录"><NotePencil size={20} /></button>
      <button className="icon-button" aria-label="打开安全与系统管理" title="安全与系统管理" onClick={() => navigate("/settings?tab=safety")}><GearSix size={20} /></button>
    </header>
  );
}
