import { beforeEach, describe, expect, it } from "vitest";
import { useStoryStore } from "./useStoryStore";

describe("story UI store", () => {
  beforeEach(() => useStoryStore.getState().resetUi());

  it("keeps only UI selection and panel preferences", () => {
    useStoryStore.getState().setActiveProjectId("project-1");
    useStoryStore.getState().selectMilestone("node-1");
    useStoryStore.getState().setAgentPanelWidth(420);

    expect(useStoryStore.getState().activeProjectId).toBe("project-1");
    expect(useStoryStore.getState().selectedMilestoneId).toBe("node-1");
    expect(useStoryStore.getState().agentPanelWidth).toBe(420);
    expect("plan" in useStoryStore.getState()).toBe(false);
  });

  it("clamps the resizable Agent panel", () => {
    useStoryStore.getState().setAgentPanelWidth(100);
    expect(useStoryStore.getState().agentPanelWidth).toBe(330);
    useStoryStore.getState().setAgentPanelWidth(900);
    expect(useStoryStore.getState().agentPanelWidth).toBe(460);
  });
});
