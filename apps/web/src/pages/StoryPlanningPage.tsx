import * as Dialog from "@radix-ui/react-dialog";
import { Check, FloppyDisk, GitBranch, List, MagicWand, PencilSimple, Plus, SlidersHorizontal, X } from "@phosphor-icons/react";
import { FormEvent, useState } from "react";
import { api } from "../api/client";
import type { PlanGenerationProposal } from "../types";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";
import { MilestoneEditor } from "../components/MilestoneEditor";
import { MilestoneTable } from "../components/MilestoneTable";
import { Timeline } from "../components/Timeline";

export function StoryPlanningPage() {
  const { project, plan, createMilestone, isLoading, isDisconnected, errorMessage, retry } = useStoryWorkspace();
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [generatingPlan, setGeneratingPlan] = useState(false);
  const [generatedPlan, setGeneratedPlan] = useState<PlanGenerationProposal | null>(null);
  const [draft, setDraft] = useState({ title: "新章节窗口", rangeMin: 1, rangeMax: 5, targetChapter: 1 });

  if (isDisconnected) return <div className="connection-state"><strong>无法连接本地数据服务</strong><p>{errorMessage ?? "请确认 FastAPI 已启动。"}</p><button onClick={retry}>重新连接</button></div>;
  if (isLoading || !plan) return <div className="connection-state"><strong>正在加载作品数据库…</strong><p>正在读取规划、对话和审计记录。</p></div>;

  const openCreate = () => {
    const sorted = [...plan.milestones].sort((a, b) => a.rangeMin - b.rangeMin);
    let start = Math.max(plan.chapterStart, (project?.currentChapter ?? 0) + 1);
    for (const node of sorted) {
      if (node.rangeMin > start) break;
      if (node.rangeMax >= start) start = node.rangeMax + 1;
    }
    start = Math.min(start, plan.chapterEnd);
    setDraft({ title: "新章节窗口", rangeMin: start, rangeMax: Math.min(start + 4, plan.chapterEnd), targetChapter: start });
    setCreateOpen(true);
  };

  const submitCreate = async (event: FormEvent) => {
    event.preventDefault();
    setCreating(true);
    try {
      await createMilestone({
        title: draft.title.trim(),
        type: "章节窗口",
        targetChapter: draft.targetChapter,
        rangeMin: draft.rangeMin,
        rangeMax: draft.rangeMax,
        importance: 3,
        note: "覆盖连续试写所需的章节规划窗口。",
        prerequisites: [`第 ${Math.max(1, draft.rangeMin - 1)} 章正式状态已确认`],
        completionConditions: [`第 ${draft.rangeMin}—${draft.rangeMax} 章的单章节拍全部完成`],
        foreshadows: [],
        contracts: [],
        chapterBeats: [],
        pace: "smooth",
      });
      setCreateOpen(false);
    } finally {
      setCreating(false);
    }
  };

  const generateArchitecturePlan = async () => {
    if (!project || project.projectKind === "demo") return;
    setGeneratingPlan(true);
    try { setGeneratedPlan(await api.createPlanGenerationProposal(project.id, plan.revision)); }
    finally { setGeneratingPlan(false); }
  };

  const decideArchitecturePlan = async (apply: boolean) => {
    if (!generatedPlan) return;
    setGeneratingPlan(true);
    try {
      if (apply) {
        await api.applyPlanGenerationProposal(generatedPlan.id, generatedPlan.revision);
        window.location.reload();
      } else {
        await api.rejectPlanGenerationProposal(generatedPlan.id, generatedPlan.revision);
        setGeneratedPlan(null);
      }
    } finally { setGeneratingPlan(false); }
  };

  return (
    <div className="planning-page">
      <header className="page-heading">
        <div><h1>故事规划中心</h1><button className="direct-edit-button"><PencilSimple size={16} />直接编辑</button><button className="direct-edit-button" onClick={openCreate}><Plus size={16} />新增规划窗口</button></div>
        <div className="view-tools"><button className="is-active" aria-label="列表视图"><List size={18} /></button><button aria-label="关系视图"><GitBranch size={18} /></button><button><SlidersHorizontal size={17} />显示设置</button></div>
      </header>
      <nav className="breadcrumb" aria-label="规划层级"><span>{plan.bookTitle}</span><i>›</i><span>{plan.volumeTitle}</span><i>›</i><strong>{plan.arcTitle}</strong></nav>
      {project?.projectKind !== "demo" && <section className="plan-architect-strip">
        <div><MagicWand /><span><strong>分层长篇规划器</strong><small>七卷范围 → 第一卷故事弧 → 第 1—5 章精确节拍 → 剧情预算台账</small></span></div>
        {!generatedPlan ? <button className="gold-action" disabled={generatingPlan} onClick={() => void generateArchitecturePlan()}>{generatingPlan ? "正在生成…" : "生成 1000 章分层规划"}</button> : <div className="plan-proposal-actions"><b className={generatedPlan.validation.valid ? "is-ready" : "is-blocked"}>{generatedPlan.validation.valid ? "范围与节拍校验通过" : "规划存在阻断项"}</b><button onClick={() => void decideArchitecturePlan(false)}><X />拒绝</button><button className="gold-action" disabled={!generatedPlan.validation.valid || generatingPlan} onClick={() => void decideArchitecturePlan(true)}><Check />应用正式规划</button></div>}
      </section>}
      <Timeline />
      <MilestoneEditor />
      <MilestoneTable />
      <div className="planning-actions"><button><span>重新分析节奏</span></button><button className="primary"><FloppyDisk size={18} />保存规划</button></div>
      <Dialog.Root open={createOpen} onOpenChange={setCreateOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="canon-lock-dialog planning-create-dialog">
            <Dialog.Title><Plus />新增章节规划窗口</Dialog.Title>
            <Dialog.Description>规划窗口用于保证准备试写的每一章都有明确边界。创建后仍可在里程碑详情中继续补充目标、前置条件和伏笔。</Dialog.Description>
            <form onSubmit={submitCreate}>
              <label><span>窗口名称</span><input aria-label="窗口名称" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} required /></label>
              <div>
                <label><span>起始章节</span><input aria-label="窗口起始章节" type="number" min={plan.chapterStart} max={plan.chapterEnd} value={draft.rangeMin} onChange={(event) => setDraft({ ...draft, rangeMin: Number(event.target.value) })} /></label>
                <label><span>结束章节</span><input aria-label="窗口结束章节" type="number" min={plan.chapterStart} max={plan.chapterEnd} value={draft.rangeMax} onChange={(event) => setDraft({ ...draft, rangeMax: Number(event.target.value) })} /></label>
                <label><span>目标章节</span><input aria-label="窗口目标章节" type="number" min={draft.rangeMin} max={draft.rangeMax} value={draft.targetChapter} onChange={(event) => setDraft({ ...draft, targetChapter: Number(event.target.value) })} /></label>
              </div>
              <footer><Dialog.Close asChild><button type="button">取消</button></Dialog.Close><button className="gold-action" type="submit" disabled={creating || !draft.title.trim() || draft.rangeMin > draft.rangeMax || draft.targetChapter < draft.rangeMin || draft.targetChapter > draft.rangeMax}>{creating ? "正在创建…" : "创建窗口"}</button></footer>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}
