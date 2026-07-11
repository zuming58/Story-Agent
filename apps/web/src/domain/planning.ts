import type { ChangeOperation, PlanNode, PlanningValidation } from "../types";

export function validateMilestones(milestones: PlanNode[]): PlanningValidation[] {
  const validations: PlanningValidation[] = [];
  const ordered = [...milestones].sort((a, b) => a.targetChapter - b.targetChapter);

  for (const milestone of milestones) {
    if (!Number.isInteger(milestone.targetChapter) || milestone.targetChapter < 1 || milestone.targetChapter > 100) {
      validations.push({
        id: `chapter-${milestone.id}`,
        severity: "error",
        rule: "PLAN_CHAPTER_BOUNDARY",
        targetId: milestone.id,
        message: `${milestone.title}的目标章节必须位于 1—100 章。`,
        suggestion: "将目标章节调整回当前卷的章节边界内。",
      });
    }
    if (milestone.rangeMin > milestone.rangeMax) {
      validations.push({
        id: `range-order-${milestone.id}`,
        severity: "error",
        rule: "PLAN_RANGE_ORDER",
        targetId: milestone.id,
        message: `${milestone.title}的允许范围起点晚于终点。`,
        suggestion: "交换范围起止值或重新设定章节窗口。",
      });
    }
    if (milestone.targetChapter < milestone.rangeMin || milestone.targetChapter > milestone.rangeMax) {
      validations.push({
        id: `range-${milestone.id}`,
        severity: "warning",
        rule: "PLAN_TARGET_RANGE",
        targetId: milestone.id,
        message: `${milestone.title}的目标章节超出允许范围。`,
        suggestion: `将目标章节放入 ${milestone.rangeMin}—${milestone.rangeMax} 章，或先调整允许范围。`,
      });
    }
    if (milestone.prerequisites.length === 0 || milestone.completionConditions.length === 0) {
      validations.push({
        id: `contract-${milestone.id}`,
        severity: "error",
        rule: "PLAN_CONTRACT_INCOMPLETE",
        targetId: milestone.id,
        message: `${milestone.title}缺少前置条件或完成条件。`,
        suggestion: "补齐里程碑契约后再保存。",
      });
    }
  }

  ordered.forEach((milestone, index) => {
    const next = ordered[index + 1];
    if (next && next.targetChapter - milestone.targetChapter < 4) {
      validations.push({
        id: `spacing-${milestone.id}-${next.id}`,
        severity: "warning",
        rule: "PLAN_MILESTONE_SPACING",
        targetId: next.id,
        message: `${milestone.title}与${next.title}间隔过短。`,
        suggestion: "拉开关键事件间隔，避免连续抢跑。",
      });
    }
  });

  return validations;
}

export function applyOperations(milestones: PlanNode[], targetId: string, operations: ChangeOperation[]): PlanNode[] {
  const selected = operations.filter((operation) => operation.selected);
  return milestones.map((milestone) => {
    if (milestone.id !== targetId) return milestone;
    return selected.reduce<PlanNode>(
      (updated, operation) => ({ ...updated, [operation.field]: operation.after }),
      milestone,
    );
  });
}

export function getPacingRiskCount(milestones: PlanNode[]): number {
  return milestones.filter((milestone) => milestone.pace !== "smooth").length > 0 ? 1 : 0;
}
