import { CaretUp, FloppyDisk, PencilSimple, Star, Trash, Warning } from "@phosphor-icons/react";
import { useEffect, useMemo, useState } from "react";
import { validateMilestones } from "../domain/planning";
import { useStoryStore } from "../store/useStoryStore";
import type { PlanNode } from "../types";

const splitLines = (value: string) => value.split("\n").map((item) => item.trim()).filter(Boolean);

export function MilestoneEditor() {
  const plan = useStoryStore((state) => state.plan);
  const selectedId = useStoryStore((state) => state.selectedMilestoneId);
  const update = useStoryStore((state) => state.updateMilestone);
  const selected = useMemo(() => plan.milestones.find((item) => item.id === selectedId) ?? plan.milestones[0], [plan.milestones, selectedId]);
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

  const save = () => {
    if (blocking) return;
    update(selected.id, candidate);
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
          <label><span>类型</span><select value={draft.type} onChange={(event) => setDraft({ ...draft, type: event.target.value as PlanNode["type"] })}><option>事件</option><option>关键事件</option><option>转折点</option><option>高潮点</option></select></label>
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
    </section>
  );
}
