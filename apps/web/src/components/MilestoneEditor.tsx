import { CaretUp, FloppyDisk, PencilSimple, Plus, Star, Trash, Warning, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import { validateMilestones } from "../domain/planning";
import type { ChapterBeat, PlanNode } from "../types";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";

const splitLines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export function MilestoneEditor() {
  const { plan, selected, updateMilestone } = useStoryWorkspace();
  if (!plan || !selected) return <section className="milestone-editor empty-editor">当前作品还没有可编辑的里程碑。</section>;
  const [draft, setDraft] = useState(selected);
  const [prerequisites, setPrerequisites] = useState(selected.prerequisites.join("\n"));
  const [conditions, setConditions] = useState(selected.completionConditions.join("\n"));

  useEffect(() => {
    setDraft(selected);
    setPrerequisites(selected.prerequisites.join("\n"));
    setConditions(selected.completionConditions.join("\n"));
  }, [selected]);

  const candidate: PlanNode = { ...draft, prerequisites: splitLines(prerequisites), completionConditions: splitLines(conditions) };
  const issues = validateMilestones(plan.milestones.map((item) => item.id === selected.id ? candidate : item)).filter((item) => item.targetId === selected.id);
  const blocking = issues.some((item) => item.severity === "error");

  const updateBeat = (index: number, changes: Partial<ChapterBeat>) => {
    setDraft((current) => ({
      ...current,
      chapterBeats: current.chapterBeats.map((beat, beatIndex) => beatIndex === index ? { ...beat, ...changes } : beat),
    }));
  };

  const addBeat = () => {
    const used = new Set(draft.chapterBeats.map((beat) => beat.chapterNumber));
    const chapterNumber = Array.from(
      { length: Math.max(0, draft.rangeMax - draft.targetChapter + 1) },
      (_, index) => draft.targetChapter + index,
    ).find((chapter) => !used.has(chapter)) ?? draft.targetChapter;
    setDraft((current) => ({
      ...current,
      chapterBeats: [...current.chapterBeats, {
        chapterNumber,
        title: `第 ${chapterNumber} 章`,
        objective: "",
        completionConditions: [],
        hooks: [],
        foreshadows: [],
        requiredCharacters: [],
        forbidden: [],
      }].sort((left, right) => left.chapterNumber - right.chapterNumber),
    }));
  };

  const save = () => {
    if (blocking) return;
    void updateMilestone(selected.id, candidate);
  };

  return (
    <section className="milestone-editor" aria-label="里程碑详情">
      <header className="editor-header">
        <strong>里程碑详情（可直接编辑）</strong>
        <div><button className="icon-button" aria-label="删除里程碑"><Trash size={17} /></button><button className="icon-button" aria-label="收起详情"><CaretUp size={18} /></button></div>
      </header>
      <div className="editor-grid">
        <div className="editor-column editor-basics">
          <label><span>里程碑名称</span><input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label>
          <label><span>类型</span><select value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value as PlanNode["type"] })}><option>事件</option><option>关键事件</option><option>转折点</option><option>高潮点</option><option>章节窗口</option></select></label>
          <div className="importance-row"><span>重要性</span><div>{[1,2,3,4,5].map((value) => <button key={value} aria-label={`重要性 ${value} 星`} onClick={() => setDraft({ ...draft, importance: value })}><Star size={18} weight={value <= draft.importance ? "fill" : "regular"} /></button>)}</div></div>
          <label className="note-field"><span>备注</span><textarea value={draft.note} onChange={(event) => setDraft({ ...draft, note: event.target.value })} /></label>
        </div>
        <div className="editor-column editor-contract">
          <div className="chapter-fields">
            <label><span>目标章节</span><input aria-label="目标章节" type="number" min="1" max="100" value={draft.targetChapter} onChange={(event) => setDraft({ ...draft, targetChapter: Number(event.target.value) })} /></label>
            <label><span>允许范围</span><div><input aria-label="允许范围起点" type="number" value={draft.rangeMin} onChange={(event) => setDraft({ ...draft, rangeMin: Number(event.target.value) })} /><em>—</em><input aria-label="允许范围终点" type="number" value={draft.rangeMax} onChange={(event) => setDraft({ ...draft, rangeMax: Number(event.target.value) })} /></div></label>
          </div>
          <div className="contract-textareas">
            <label><span>前置条件</span><textarea value={prerequisites} onChange={(event) => setPrerequisites(event.target.value)} /></label>
            <label><span>完成条件</span><textarea value={conditions} onChange={(event) => setConditions(event.target.value)} /></label>
          </div>
          <div className="editor-bottom-row">
            <div className="foreshadow-chips"><span>关联伏笔</span><div>{draft.foreshadows.map((item) => <button key={item}>{item}<PencilSimple size={12} /></button>)}</div></div>
            <button className="save-button" onClick={save} disabled={blocking}><FloppyDisk size={17} />保存规划</button>
          </div>
          {issues.length > 0 && <div className={`validation-banner${blocking ? " is-blocking" : ""}`}><Warning size={17} /><span>{issues[0].message} {issues[0].suggestion}</span></div>}
        </div>
      </div>
      {draft.type === "章节窗口" && <section className="chapter-beat-editor" aria-label="单章节拍">
        <header>
          <div><strong>单章节拍</strong><span>窗口总目标不会直接写进单章；只有对应章节的节拍会进入章节契约。</span></div>
          <button type="button" className="direct-edit-button" onClick={addBeat}><Plus size={15} />新增节拍</button>
        </header>
        {draft.chapterBeats.length === 0
          ? <div className="chapter-beat-empty"><Warning size={18} /><span>尚未拆分单章节拍，试写检查会阻止自动生成，避免把整个窗口一次写完。</span></div>
          : <div className="chapter-beat-list">{draft.chapterBeats.map((beat, index) => <article className="chapter-beat-card" key={`${beat.chapterNumber}-${index}`}>
              <div className="chapter-beat-card-head">
                <label><span>章节</span><input type="number" value={beat.chapterNumber} min={draft.rangeMin} max={draft.rangeMax} onChange={(event) => updateBeat(index, { chapterNumber: Number(event.target.value) })} /></label>
                <label className="chapter-beat-title"><span>标题</span><input value={beat.title} onChange={(event) => updateBeat(index, { title: event.target.value })} /></label>
                <button type="button" className="icon-button" aria-label={`删除第 ${beat.chapterNumber} 章节拍`} onClick={() => setDraft((current) => ({ ...current, chapterBeats: current.chapterBeats.filter((_, beatIndex) => beatIndex !== index) }))}><X size={16} /></button>
              </div>
              <label className="chapter-beat-objective"><span>本章唯一推进目标</span><textarea value={beat.objective} onChange={(event) => updateBeat(index, { objective: event.target.value })} /></label>
              <div className="chapter-beat-fields">
                <label><span>完成条件（每行一项）</span><textarea value={beat.completionConditions.join("\n")} onChange={(event) => updateBeat(index, { completionConditions: splitLines(event.target.value) })} /></label>
                <label><span>章末钩子（每行一项）</span><textarea value={beat.hooks.join("\n")} onChange={(event) => updateBeat(index, { hooks: splitLines(event.target.value) })} /></label>
                <label><span>出场人物（每行一名）</span><textarea value={beat.requiredCharacters.join("\n")} onChange={(event) => updateBeat(index, { requiredCharacters: splitLines(event.target.value) })} /></label>
                <label><span>本章禁止提前完成</span><textarea value={beat.forbidden.join("\n")} onChange={(event) => updateBeat(index, { forbidden: splitLines(event.target.value) })} /></label>
              </div>
            </article>)}</div>}
      </section>}
    </section>
  );
}
