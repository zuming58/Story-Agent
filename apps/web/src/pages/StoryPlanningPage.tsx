import { FloppyDisk, GitBranch, List, PencilSimple, SlidersHorizontal } from "@phosphor-icons/react";
import { useEffect } from "react";
import { useStoryStore } from "../store/useStoryStore";
import { MilestoneEditor } from "../components/MilestoneEditor";
import { MilestoneTable } from "../components/MilestoneTable";
import { Timeline } from "../components/Timeline";

export function StoryPlanningPage() {
  const plan = useStoryStore((state) => state.plan);
  const notice = useStoryStore((state) => state.notice);
  const clearNotice = useStoryStore((state) => state.clearNotice);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(clearNotice, 2800);
    return () => window.clearTimeout(timer);
  }, [notice, clearNotice]);

  return (
    <div className="planning-page">
      <header className="page-heading">
        <div><h1>故事规划中心</h1><button className="direct-edit-button"><PencilSimple size={16} />直接编辑</button></div>
        <div className="view-tools"><button className="is-active" aria-label="列表视图"><List size={18} /></button><button aria-label="关系视图"><GitBranch size={18} /></button><button><SlidersHorizontal size={17} />显示设置</button></div>
      </header>
      <nav className="breadcrumb" aria-label="规划层级"><span>{plan.bookTitle}</span><i>›</i><span>{plan.volumeTitle}</span><i>›</i><strong>{plan.arcTitle}</strong></nav>
      <Timeline />
      <MilestoneEditor />
      <MilestoneTable />
      <div className="planning-actions"><button><span>重新分析节奏</span></button><button className="primary"><FloppyDisk size={18} />保存规划</button></div>
      {notice && <div className="toast-notice" role="status">{notice}</div>}
    </div>
  );
}
