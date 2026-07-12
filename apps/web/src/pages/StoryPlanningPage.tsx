import { FloppyDisk, GitBranch, List, PencilSimple, SlidersHorizontal } from "@phosphor-icons/react";
import { useEffect } from "react";
import { useStoryStore } from "../store/useStoryStore";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { MilestoneEditor } from "../components/MilestoneEditor";
import { MilestoneTable } from "../components/MilestoneTable";
import { Timeline } from "../components/Timeline";

export function StoryPlanningPage() {
  const { plan, isLoading, isDisconnected, errorMessage, retry } = useStoryWorkspace();
  const notice = useStoryStore((state) => state.notice);
  const setNotice = useStoryStore((state) => state.setNotice);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2800);
    return () => window.clearTimeout(timer);
  }, [notice, setNotice]);

  if (isDisconnected) return <div className="connection-state"><strong>无法连接本地数据服务</strong><p>{errorMessage ?? "请确认 FastAPI 已启动。"}</p><button onClick={retry}>重新连接</button></div>;
  if (isLoading || !plan) return <div className="connection-state"><strong>正在加载作品数据库…</strong><p>正在读取规划、对话和审计记录。</p></div>;

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
