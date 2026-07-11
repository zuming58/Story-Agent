import { CaretDown, Clock, GearSix, NotePencil } from "@phosphor-icons/react";
import { useStoryStore } from "../store/useStoryStore";

export function TopBar() {
  const project = useStoryStore((state) => state.project);
  const resetDemo = useStoryStore((state) => state.resetDemo);
  const progress = (project.currentChapter / project.totalChapters) * 100;

  return (
    <header className="topbar">
      <button className="project-switcher">
        <strong>{project.title}</strong>
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
        <span>{project.model} · 在线</span>
        <i aria-label="模型在线" />
      </div>
      <span className="topbar-divider" />
      <div className="automation-status"><Clock size={17} /><span>{project.automationSchedule}</span></div>
      <button className="icon-button" aria-label="工作记录"><NotePencil size={20} /></button>
      <button className="icon-button" aria-label="重置演示数据" onClick={resetDemo}><GearSix size={20} /></button>
    </header>
  );
}
