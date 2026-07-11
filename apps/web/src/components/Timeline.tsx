import { BookOpen, LinkSimple, Target } from "@phosphor-icons/react";
import { useMemo } from "react";
import { useStoryStore } from "../store/useStoryStore";
import { useStoryWorkspace } from "../context/StoryWorkspaceContext";

const windows = [
  { label: "开场", range: "1–20", start: 1, end: 20 },
  { label: "发展", range: "21–40", start: 21, end: 40 },
  { label: "中段", range: "41–60", start: 41, end: 60 },
  { label: "高潮", range: "61–80", start: 61, end: 80 },
  { label: "收束", range: "81–100", start: 81, end: 100 },
];

const position = (chapter: number) => `${Math.min(99, Math.max(1, chapter))}%`;

export function Timeline() {
  const { plan, proposal } = useStoryWorkspace();
  const milestones = plan?.milestones ?? [];
  const markers = plan?.markers ?? [];
  const selectedId = useStoryStore((state) => state.selectedMilestoneId);
  const select = useStoryStore((state) => state.selectMilestone);
  const proposedChapter = useMemo(() => {
    if (!proposal || proposal.status !== "pending") return null;
    const operation = proposal.operations.find((item) => item.field === "targetChapter");
    return operation?.after ?? null;
  }, [proposal]);

  return (
    <section className="timeline-panel" aria-label="第一卷章节时间轴">
      <div className="timeline-title-row"><strong>章节尺规（1–100）</strong><span>拖动节点或在下方直接编辑</span></div>
      <div className="chapter-ruler">
        {[1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map((chapter) => <span key={chapter} style={{ left: position(chapter) }}>{chapter}</span>)}
      </div>
      <div className="chapter-windows">
        {windows.map((window) => <div key={window.label}><span>{window.label}</span><small>{window.range}</small></div>)}
      </div>
      <div className="milestone-track">
        <span className="track-line" />
        {milestones.map((milestone) => (
          <button
            key={milestone.id}
            className={`milestone-node${selectedId === milestone.id ? " is-selected" : ""}`}
            style={{ left: position(milestone.targetChapter) }}
            onClick={() => select(milestone.id)}
            aria-label={`选择里程碑：${milestone.title}，第 ${milestone.targetChapter} 章`}
          >
            <span className="node-diamond"><Target size={13} weight="fill" /></span>
            <strong>{milestone.targetChapter}</strong><small>{milestone.title}</small>
          </button>
        ))}
        {proposedChapter && <span className="proposal-ghost" style={{ left: position(proposedChapter) }}><i />建议 {proposedChapter} 章</span>}
      </div>
      <div className="timeline-legend">
        <span><LinkSimple size={16} />钩子</span><span><BookOpen size={16} />伏笔</span><span className="dash-legend" />目标范围
        <span className="pace-label">节奏状态</span><span className="pace pace-smooth" />顺畅<span className="pace pace-slow" />偏慢<span className="pace pace-fast" />偏快
      </div>
      <div className="marker-lanes">
        <div className="lane-row"><strong>钩子 & 伏笔分布</strong><div className="lane-track">{markers.map((marker) => <span key={marker.id} className={`marker marker-${marker.kind}`} style={{ left: position(marker.chapter) }} title={marker.label}>{marker.kind === "foreshadow" ? <BookOpen size={16} /> : <LinkSimple size={16} />}</span>)}</div></div>
        <div className="lane-row"><strong>目标范围（建议章节）</strong><div className="lane-track">{milestones.map((milestone) => <span key={milestone.id} className="range-marker" style={{ left: position(milestone.rangeMin), width: `calc(${milestone.rangeMax - milestone.rangeMin}% + 12px)` }}>{milestone.rangeMin}–{milestone.rangeMax}</span>)}</div></div>
        <div className="lane-row"><strong>节奏状态</strong><div className="lane-track">{windows.map((window, index) => <span key={window.label} className={`pace-segment pace-${["smooth", "slow", "fast", "smooth", "fast"][index]}`} style={{ left: `${index * 20}%`, width: "19.5%" }} />)}</div></div>
      </div>
    </section>
  );
}
