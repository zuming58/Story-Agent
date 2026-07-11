import { describe, expect, it } from "vitest";
import { storyPlan } from "../data/mockStory";
import { applyOperations, validateMilestones } from "./planning";

describe("planning validation", () => {
  it("detects out-of-range targets and missing contracts", () => {
    const invalid = storyPlan.milestones.map((milestone, index) =>
      index === 0
        ? { ...milestone, targetChapter: 112, prerequisites: [], completionConditions: [] }
        : milestone,
    );
    const result = validateMilestones(invalid);

    expect(result.some((item) => item.rule === "PLAN_CHAPTER_BOUNDARY")).toBe(true);
    expect(result.some((item) => item.rule === "PLAN_CONTRACT_INCOMPLETE")).toBe(true);
  });

  it("keeps the original plan unchanged when applying selected operations", () => {
    const original = storyPlan.milestones;
    const updated = applyOperations(original, "milestone-paper-man", [
      { id: "target", field: "targetChapter", label: "目标章节", before: 18, after: 22, selected: true },
      { id: "range", field: "rangeMin", label: "范围起点", before: 16, after: 20, selected: false },
    ]);

    expect(original.find((item) => item.id === "milestone-paper-man")?.targetChapter).toBe(18);
    expect(updated.find((item) => item.id === "milestone-paper-man")?.targetChapter).toBe(22);
    expect(updated.find((item) => item.id === "milestone-paper-man")?.rangeMin).toBe(16);
  });
});
