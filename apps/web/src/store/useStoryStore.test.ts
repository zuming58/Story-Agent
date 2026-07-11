import { beforeEach, describe, expect, it } from "vitest";
import { useStoryStore } from "./useStoryStore";

describe("story store change lifecycle", () => {
  beforeEach(() => {
    useStoryStore.getState().resetDemo();
  });

  it("applies a reviewed AI proposal and can undo it", () => {
    const initialTarget = useStoryStore.getState().plan.milestones.find((item) => item.id === "milestone-paper-man")?.targetChapter;
    expect(initialTarget).toBe(18);

    useStoryStore.getState().applyProposal();
    expect(useStoryStore.getState().plan.milestones.find((item) => item.id === "milestone-paper-man")?.targetChapter).toBe(22);
    expect(useStoryStore.getState().history).toHaveLength(1);

    useStoryStore.getState().undo();
    expect(useStoryStore.getState().plan.milestones.find((item) => item.id === "milestone-paper-man")?.targetChapter).toBe(18);
  });

  it("rejects a proposal without changing the plan", () => {
    useStoryStore.getState().rejectProposal();
    expect(useStoryStore.getState().plan.milestones.find((item) => item.id === "milestone-paper-man")?.targetChapter).toBe(18);
    expect(useStoryStore.getState().proposal?.status).toBe("rejected");
  });
});
