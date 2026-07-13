import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, Circle, FolderOpen, Plus, RocketLaunch, X } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import type { StoryMode } from "../types";
import { api } from "../api/client";

export function ProjectOverviewPage() {
  const { projects, project, selectProject, createProject, isDisconnected, retry } = useStoryWorkspace();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<StoryMode>("long-form");
  const [chapters, setChapters] = useState(100);
  const navigate = useNavigate();
  const readinessQuery = useQuery({ queryKey: ["trial-readiness", project?.id, 1], queryFn: () => api.trialReadiness(project!.id, 1), enabled: Boolean(project) });
  const runsQuery = useQuery({ queryKey: ["automation-runs", project?.id], queryFn: () => api.automationRuns(project!.id), enabled: Boolean(project) });
  const checks = readinessQuery.data?.checks ?? [];
  const readyCode = (code: string) => checks.some((item) => item.code === code && item.status === "ready");
  const guide = project ? [
    { label: "配置模型", detail: "Provider、密钥与角色路由", done: readyCode("TRIAL_MODELS_READY"), path: "/settings" },
    { label: "完成 Canon", detail: "设定结构化并锁定", done: readyCode("TRIAL_CANON_READY"), path: "/canon" },
    { label: "检查规划", detail: "覆盖下一试写窗口", done: readyCode("TRIAL_PLAN_READY"), path: "/planning" },
    { label: "生成第一章", detail: "契约、正文与质量门", done: project.currentChapter > 0, path: "/writing" },
    { label: "完成质量复核", detail: "正式提交才更新状态", done: project.currentChapter > 0, path: "/quality" },
    { label: "连续试写", detail: "从 3—5 章开始验证", done: Boolean(runsQuery.data?.some((run) => run.status === "completed" && run.plannedCount >= 3)), path: "/automation" },
  ] : [];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const created = await createProject({ title, mode, totalChapters: chapters });
    setOpen(false); setTitle(""); selectProject(created.id); navigate("/planning");
  };

  if (isDisconnected) return <div className="connection-state"><strong>本地作品库暂时不可用</strong><button onClick={retry}>重新连接</button></div>;

  return <div className="project-overview-page">
    <header><div><span className="placeholder-kicker"><BookOpen size={19} />本地作品库</span><h1>选择要继续创作的故事</h1><p>每部作品拥有独立 SQLite、Canon 目录和备份空间。</p></div>
      <Dialog.Root open={open} onOpenChange={setOpen}><Dialog.Trigger asChild><button className="project-create-button"><Plus size={18} />新建作品</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="project-dialog"><Dialog.Title>创建本地作品</Dialog.Title><Dialog.Description>系统会建立独立目录、数据库和 Canon 文件。</Dialog.Description><form onSubmit={(event) => void submit(event)}><label>作品名称<input value={title} onChange={(event) => setTitle(event.target.value)} autoFocus required /></label><label>创作模式<select value={mode} onChange={(event) => setMode(event.target.value as StoryMode)}><option value="long-form">长篇网文</option><option value="short-form">短篇小说</option><option value="short-drama">短剧项目</option></select></label><label>计划章节<input type="number" min="1" max="5000" value={chapters} onChange={(event) => setChapters(Number(event.target.value))} /></label><div className="dialog-actions"><Dialog.Close asChild><button type="button">取消</button></Dialog.Close><button className="primary" type="submit" disabled={!title.trim()}>创建作品</button></div></form><Dialog.Close className="dialog-close" aria-label="关闭"><X size={18} /></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
    </header>
    {project && <section className="trial-guide"><header><div><RocketLaunch /><strong>第一次试写</strong></div><span>{guide.filter((item) => item.done).length}/{guide.length} 已完成</span></header><div>{guide.map((item, index) => <button key={item.label} className={item.done ? "is-done" : ""} onClick={() => navigate(item.path)}><i>{item.done ? <Check weight="bold" /> : <Circle />}</i><small>STEP {index + 1}</small><strong>{item.label}</strong><span>{item.detail}</span></button>)}</div></section>}
    <section className="project-grid">{projects.map((item) => <button key={item.id} className={`project-card${project?.id === item.id ? " is-active" : ""}`} onClick={() => { selectProject(item.id); navigate("/planning"); }}><div className="project-card-icon"><BookOpen size={28} weight="duotone" /></div><div><strong>{item.title}</strong><span>{item.mode === "long-form" ? "长篇网文" : item.mode === "short-form" ? "短篇小说" : "短剧项目"} · {item.currentChapter}/{item.totalChapters} 章</span><small><FolderOpen size={13} />{item.folderPath}</small></div></button>)}</section>
  </div>;
}
