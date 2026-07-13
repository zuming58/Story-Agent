import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

interface StoryUiState {
  activeProjectId: string | null;
  selectedMilestoneId: string | null;
  selectedChapterNumber: number;
  selectedChapterJobId: string | null;
  agentScopeLabels: string[];
  agentSelection: string;
  agentPanelCollapsed: boolean;
  agentPanelWidth: number;
  notice: string | null;
  setActiveProjectId: (id: string | null) => void;
  selectMilestone: (id: string) => void;
  selectChapter: (chapter: number, jobId?: string | null) => void;
  setAgentContext: (labels: string[], selection?: string) => void;
  setAgentPanelCollapsed: (collapsed: boolean) => void;
  setAgentPanelWidth: (width: number) => void;
  setNotice: (notice: string | null) => void;
  resetUi: () => void;
}

const defaults = {
  activeProjectId: null,
  selectedMilestoneId: null,
  selectedChapterNumber: 1,
  selectedChapterJobId: null,
  agentScopeLabels: [],
  agentSelection: "",
  agentPanelCollapsed: false,
  agentPanelWidth: 374,
  notice: null,
};

export const useStoryStore = create<StoryUiState>()(
  persist(
    (set) => ({
      ...defaults,
      setActiveProjectId: (activeProjectId) => set({ activeProjectId, selectedMilestoneId: null, selectedChapterNumber: 1, selectedChapterJobId: null, agentScopeLabels: [], agentSelection: "" }),
      selectMilestone: (selectedMilestoneId) => set({ selectedMilestoneId }),
      selectChapter: (selectedChapterNumber, selectedChapterJobId = null) => set({ selectedChapterNumber, selectedChapterJobId }),
      setAgentContext: (agentScopeLabels, agentSelection = "") => set({ agentScopeLabels, agentSelection }),
      setAgentPanelCollapsed: (agentPanelCollapsed) => set({ agentPanelCollapsed }),
      setAgentPanelWidth: (agentPanelWidth) => set({ agentPanelWidth: Math.min(460, Math.max(330, agentPanelWidth)) }),
      setNotice: (notice) => set({ notice }),
      resetUi: () => set(defaults),
    }),
    {
      name: "story-agent-ui-v2",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        activeProjectId: state.activeProjectId,
        selectedChapterNumber: state.selectedChapterNumber,
        selectedChapterJobId: state.selectedChapterJobId,
        agentPanelCollapsed: state.agentPanelCollapsed,
        agentPanelWidth: state.agentPanelWidth,
      }),
    },
  ),
);
