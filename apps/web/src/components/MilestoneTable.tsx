import { DotsThree, PencilSimple } from "@phosphor-icons/react";
import { useStoryStore } from "../store/useStoryStore";

export function MilestoneTable() {
  const milestones = useStoryStore((state) => state.plan.milestones);
  const selectedId = useStoryStore((state) => state.selectedMilestoneId);
  const select = useStoryStore((state) => state.selectMilestone);
  return (
    <section className="milestone-table-section">
      <header><strong>里程碑列表</strong><span>（{milestones.length}）</span></header>
      <div className="table-wrap">
        <table>
          <thead><tr><th>序号</th><th>里程碑名称</th><th>目标章节</th><th>允许范围</th><th>类型</th><th>节奏状态</th><th>关联契约</th><th>操作</th></tr></thead>
          <tbody>{milestones.map((milestone, index) => (
            <tr key={milestone.id} className={selectedId === milestone.id ? "is-selected" : ""} onClick={() => select(milestone.id)}>
              <td>{index + 1}</td><td>{milestone.title}</td><td>{milestone.targetChapter}</td><td>{milestone.rangeMin}–{milestone.rangeMax}</td><td>{milestone.type}</td>
              <td><span className={`table-pace pace-${milestone.pace}`} />{milestone.pace === "smooth" ? "顺畅" : milestone.pace === "slow" ? "偏慢" : "偏快"}</td>
              <td>{milestone.contracts.join("、")}</td><td><button className="icon-button" aria-label={`编辑${milestone.title}`}><PencilSimple size={15} /></button><button className="icon-button" aria-label="更多操作"><DotsThree size={17} /></button></td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
