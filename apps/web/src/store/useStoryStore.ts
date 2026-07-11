import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";
import { initialMessages, initialProposal, project, storyPlan } from "../data/mockStory";
import { applyOperations } from "../domain/planning";
import type { AgentMessage, ChangeProposal, PlanNode, ProjectSummary, StoryPlan } from "../types";

interface HistoryEntry {
  milestones: PlanNode[];
  label: string;
}

interface StoryState {
  project: ProjectSummary;
  plan: StoryPlan;
  selectedMilestoneId: string;
  agentMessages: AgentMessage[];
  agentStatus: "idle" | "thinking" | "error";
  agentPanelCollapsed: boolean;
  agentPanelWidth: number;
  proposal: ChangeProposal | null;
  history: HistoryEntry[];
  notice: string | null;
  selectMilestone: (id: string) => void;
  updateMilestone: (id: string, changes: Partial<PlanNode>) => void;
  addMessage: (message: AgentMessage) => void;
  setAgentStatus: (status: StoryState["agentStatus"]) => void;
  setAgentPanelCollapsed: (collapsed: boolean) => void;
  setAgentPanelWidth: (width: number) => void;
  setProposal: (proposal: ChangeProposal | null) => void;
  toggleProposalOperation: (operationId: string) => void;
  selectAllProposalOperations: () => void;
  applyProposal: () => void;
  rejectProposal: () => void;
  undo: () => void;
  clearNotice: () => void;
  resetDemo: () => void;
}

const initialState = () => ({
  project,
  plan: storyPlan,
  selectedMilestoneId: "milestone-paper-man",
  agentMessages: initialMessages,
  agentStatus: "idle" as const,
  agentPanelCollapsed: false,
  agentPanelWidth: 374,
  proposal: initialProposal,
  history: [] as HistoryEntry[],
  notice: null as string | null,
});

export const useStoryStore = create<StoryState>()(
  persist(
    (set, get) => ({
      ...initialState(),
      selectMilestone: (id) => set({ selectedMilestoneId: id }),
      updateMilestone: (id, changes) => {
        const { plan, history } = get();
        const previous = plan.milestones;
        const milestones = previous.map((milestone) =>
          milestone.id === id ? { ...milestone, ...changes } : milestone,
        );
        set({
          plan: { ...plan, milestones },
          history: [...history, { milestones: previous, label: "直接编辑里程碑" }].slice(-20),
          notice: "规划已保存，并重新执行边界检查。",
        });
      },
      addMessage: (message) => set((state) => ({ agentMessages: [...state.agentMessages, message] })),
      setAgentStatus: (agentStatus) => set({ agentStatus }),
      setAgentPanelCollapsed: (agentPanelCollapsed) => set({ agentPanelCollapsed }),
      setAgentPanelWidth: (agentPanelWidth) => set({ agentPanelWidth: Math.min(460, Math.max(330, agentPanelWidth)) }),
      setProposal: (proposal) => set({ proposal }),
      toggleProposalOperation: (operationId) =>
        set((state) => ({
          proposal: state.proposal
            ? {
                ...state.proposal,
                operations: state.proposal.operations.map((operation) =>
                  operation.id === operationId ? { ...operation, selected: !operation.selected } : operation,
                ),
              }
            : null,
        })),
      selectAllProposalOperations: () =>
        set((state) => ({
          proposal: state.proposal
            ? { ...state.proposal, operations: state.proposal.operations.map((operation) => ({ ...operation, selected: true })) }
            : null,
        })),
      applyProposal: () => {
        const { proposal, plan, history } = get();
        if (!proposal || !proposal.operations.some((operation) => operation.selected)) return;
        const previous = plan.milestones;
        set({
          plan: { ...plan, milestones: applyOperations(previous, proposal.targetId, proposal.operations) },
          proposal: { ...proposal, status: "accepted" },
          history: [...history, { milestones: previous, label: "接受 AI 修改" }].slice(-20),
          notice: "AI 修改已应用；3 个章节契约与 1 条伏笔已标记为待同步。",
        });
      },
      rejectProposal: () =>
        set((state) => ({
          proposal: state.proposal ? { ...state.proposal, status: "rejected" } : null,
          notice: "修改提案已拒绝，正式规划未发生变化。",
        })),
      undo: () => {
        const { history, plan } = get();
        const previous = history.at(-1);
        if (!previous) return;
        set({
          plan: { ...plan, milestones: previous.milestones },
          history: history.slice(0, -1),
          proposal: initialProposal,
          notice: `已撤销：${previous.label}`,
        });
      },
      clearNotice: () => set({ notice: null }),
      resetDemo: () => set(initialState()),
    }),
    {
      name: "story-agent-prototype-v1",
      storage: createJSONStorage(() => localStorage),
      version: 1,
      partialize: (state) => ({
        plan: state.plan,
        selectedMilestoneId: state.selectedMilestoneId,
        agentMessages: state.agentMessages,
        agentPanelCollapsed: state.agentPanelCollapsed,
        agentPanelWidth: state.agentPanelWidth,
        proposal: state.proposal,
        history: state.history,
      }),
    },
  ),
);
