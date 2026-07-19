import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { BookOpen, Check, Circle, CircleNotch, FolderOpen, PencilSimple, Plus, RocketLaunch, X } from "@phosphor-icons/react";
import { FormEvent, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import type { ProjectSummary, StoryMode } from "../types";

function untitledProjectName() {
  const now = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `未命名作品 ${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
}

function readableError(error: unknown) {
  return error instanceof Error ? error.message : "操作没有完成，请稍后重试。";
}

export function ProjectOverviewPage() {
  const { projects, project, selectProject, createProject, updateProject, isDisconnected, retry } = useStoryWorkspace();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [mode, setMode] = useState<StoryMode>("long-form");
  const [chapters, setChapters] = useState(100);
  const [isCreating, setIsCreating] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const creatingRef = useRef(false);
  const [renameTarget, setRenameTarget] = useState<ProjectSummary | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [isRenaming, setIsRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const renamingRef = useRef(false);
  const navigate = useNavigate();
  const readinessQuery = useQuery({ queryKey: ["trial-readiness", project?.id, 1], queryFn: () => api.trialReadiness(project!.id, 1), enabled: Boolean(project) });
  const incubationQuery = useQuery({ queryKey: ["incubator-readiness", project?.id], queryFn: () => api.incubationReadiness(project!.id), enabled: Boolean(project) });
  const runsQuery = useQuery({ queryKey: ["automation-runs", project?.id], queryFn: () => api.automationRuns(project!.id), enabled: Boolean(project) });
  const checks = readinessQuery.data?.checks ?? [];
  const readyCode = (code: string) => checks.some((item) => item.code === code && item.status === "ready");
  const guide = project ? [
    { label: "配置模型", detail: "Provider、密钥与角色路由", done: readyCode("TRIAL_MODELS_READY"), path: "/settings" },
    { label: "完成创意孵化", detail: "调研、共创与三开篇实验", done: incubationQuery.data?.ready === true, path: "/incubator" },
    { label: "完成 Canon", detail: "设定结构化并锁定", done: readyCode("TRIAL_CANON_READY"), path: "/canon" },
    { label: "检查规划", detail: "覆盖下一试写窗口", done: readyCode("TRIAL_PLAN_READY"), path: "/planning" },
    { label: "生成第一章", detail: "契约、正文与质量门", done: project.currentChapter > 0, path: "/writing" },
    { label: "完成质量复核", detail: "正式提交才更新状态", done: project.currentChapter > 0, path: "/quality" },
    { label: "连续试写", detail: "从 3—5 章开始验证", done: Boolean(runsQuery.data?.some((run) => run.status === "completed" && run.plannedCount >= 3)), path: "/automation" },
  ] : [];

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (creatingRef.current) return;
    const safeChapters = Number(chapters);
    if (!Number.isInteger(safeChapters) || safeChapters < 1 || safeChapters > (mode === "short-form" ? 30 : 5000)) {
      setCreateError(mode === "short-form" ? "短篇小说的计划章节需在 1—30 章之间。" : "计划章节需在 1—5000 章之间。");
      return;
    }
    creatingRef.current = true;
    setIsCreating(true);
    setCreateError(null);
    try {
      const created = await createProject({ title: title.trim() || untitledProjectName(), mode, totalChapters: safeChapters });
      setOpen(false);
      setTitle("");
      selectProject(created.id);
      navigate("/incubator");
    } catch (error) {
      setCreateError(readableError(error));
    } finally {
      creatingRef.current = false;
      setIsCreating(false);
    }
  };

  const beginRename = (item: ProjectSummary) => {
    setRenameTarget(item);
    setRenameTitle(item.title);
    setRenameError(null);
  };

  const submitRename = async (event: FormEvent) => {
    event.preventDefault();
    if (!renameTarget || renamingRef.current) return;
    const nextTitle = renameTitle.trim();
    if (!nextTitle) {
      setRenameError("作品名称不能为空。暂时没想好时，可以保留“未命名作品”作为临时名称。");
      return;
    }
    renamingRef.current = true;
    setIsRenaming(true);
    setRenameError(null);
    try {
      await updateProject(renameTarget.id, { title: nextTitle });
      setRenameTarget(null);
    } catch (error) {
      setRenameError(readableError(error));
    } finally {
      renamingRef.current = false;
      setIsRenaming(false);
    }
  };

  if (isDisconnected) return <div className="connection-state"><strong>本地作品库暂时不可用</strong><button onClick={retry}>重新连接</button></div>;

  return <div className="project-overview-page">
    <header><div><span className="placeholder-kicker"><BookOpen size={19} />本地作品库</span><h1>选择要继续创作的故事</h1><p>每部作品拥有独立 SQLite、Canon 目录和备份空间。</p></div>
      <Dialog.Root open={open} onOpenChange={(nextOpen) => { if (!isCreating) { setOpen(nextOpen); setCreateError(null); } }}><Dialog.Trigger asChild><button className="project-create-button"><Plus size={18} />新建作品</button></Dialog.Trigger><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="project-dialog"><Dialog.Title>创建本地作品</Dialog.Title><Dialog.Description>系统会建立独立目录、数据库和 Canon 文件；创建后进入故事构思与设定。</Dialog.Description><form onSubmit={(event) => void submit(event)}><label>作品名称 <small>可稍后修改</small><input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="暂时没想好可留空，系统会使用临时名称" maxLength={200} autoFocus /></label><p className="project-dialog-hint">书名不需要现在定稿。进入创意孵化后，可以先和 AI 把故事想清楚，再回到作品库修改名称。</p><label>创作模式<select value={mode} onChange={(event) => { const nextMode = event.target.value as StoryMode; setMode(nextMode); if (nextMode === "short-form" && chapters > 30) setChapters(20); }}><option value="long-form">长篇网文</option><option value="short-form">短篇小说</option><option value="short-drama">短剧项目</option></select></label><label>计划章节<input type="number" min="1" max={mode === "short-form" ? 30 : 5000} value={chapters} onChange={(event) => setChapters(Number(event.target.value))} /></label>{createError && <p className="project-dialog-error" role="alert">{createError}</p>}<div className="dialog-actions"><Dialog.Close asChild><button type="button" disabled={isCreating}>取消</button></Dialog.Close><button className="primary" type="submit" disabled={isCreating}>{isCreating ? <><CircleNotch className="spin" size={17} />正在创建，请稍候…</> : "创建并开始构思"}</button></div></form><Dialog.Close className="dialog-close" aria-label="关闭" disabled={isCreating}><X size={18} /></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
    </header>
    {project && <section className="trial-guide"><header><div><RocketLaunch /><strong>第一次试写</strong></div><span>{guide.filter((item) => item.done).length}/{guide.length} 已完成</span></header><div>{guide.map((item, index) => <button key={item.label} className={item.done ? "is-done" : ""} onClick={() => navigate(item.path)}><i>{item.done ? <Check weight="bold" /> : <Circle />}</i><small>STEP {index + 1}</small><strong>{item.label}</strong><span>{item.detail}</span></button>)}</div></section>}
    <section className="project-grid">{projects.map((item) => <article key={item.id} className={`project-card-shell${project?.id === item.id ? " is-active" : ""}`}><button className="project-card" onClick={() => { selectProject(item.id); navigate(item.currentChapter === 0 && item.projectKind !== "demo" ? "/incubator" : "/planning"); }}><div className="project-card-icon"><BookOpen size={28} weight="duotone" /></div><div><strong>{item.title}{item.projectKind === "demo" && <em className="project-kind-badge">示例·从第36章开始</em>}</strong><span>{item.mode === "long-form" ? "长篇网文" : item.mode === "short-form" ? "短篇小说" : "短剧项目"} · {item.currentChapter}/{item.totalChapters} 章</span><small><FolderOpen size={13} />{item.folderPath}</small></div></button><button className="project-rename-button" aria-label={`修改《${item.title}》书名`} title="修改书名" onClick={() => beginRename(item)}><PencilSimple size={15} /></button></article>)}</section>

    <Dialog.Root open={Boolean(renameTarget)} onOpenChange={(nextOpen) => { if (!nextOpen && !isRenaming) setRenameTarget(null); }}><Dialog.Portal><Dialog.Overlay className="dialog-overlay" /><Dialog.Content className="project-dialog project-rename-dialog"><Dialog.Title>修改作品名称</Dialog.Title><Dialog.Description>只修改作品显示名称，不会破坏现有章节、Canon、规划或历史记录。</Dialog.Description><form onSubmit={(event) => void submitRename(event)}><label>新的作品名称<input value={renameTitle} onChange={(event) => setRenameTitle(event.target.value)} maxLength={200} autoFocus /></label>{renameError && <p className="project-dialog-error" role="alert">{renameError}</p>}<div className="dialog-actions"><button type="button" disabled={isRenaming} onClick={() => setRenameTarget(null)}>取消</button><button className="primary" type="submit" disabled={isRenaming || !renameTitle.trim()}>{isRenaming ? <><CircleNotch className="spin" size={17} />正在保存…</> : "保存新名称"}</button></div></form><Dialog.Close className="dialog-close" aria-label="关闭" disabled={isRenaming}><X size={18} /></Dialog.Close></Dialog.Content></Dialog.Portal></Dialog.Root>
  </div>;
}
