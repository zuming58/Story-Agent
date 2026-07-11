import type { AgentMessage, ChangeProposal, PlanNode } from "../types";
import { initialProposal } from "../data/mockStory";

const wait = (milliseconds: number) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));

export interface MockAgentResponse {
  message: AgentMessage;
  proposal?: ChangeProposal;
}

export async function sendMockAgentMessage(input: string, selected: PlanNode): Promise<MockAgentResponse> {
  await wait(520);
  const requestsChange = /调整|重排|修改|节奏|提前|推后|逻辑/.test(input);
  const content = requestsChange
    ? `我已重新检查“${selected.title}”的章节窗口、前置条件和伏笔依赖。建议采用右侧修改提案，确认后才会写入规划。`
    : `我已读取当前作用域。关于“${selected.title}”，现有规划的前置条件完整；你可以继续说明希望强化的冲突或情绪。`;

  return {
    message: {
      id: `message-${Date.now()}`,
      role: "assistant",
      content,
      timestamp: new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" }),
    },
    proposal: requestsChange
      ? {
          ...initialProposal,
          id: `proposal-${Date.now()}`,
          targetId: selected.id,
          targetTitle: selected.title,
          operations: initialProposal.operations.map((operation) => ({
            ...operation,
            before: selected[operation.field],
          })),
        }
      : undefined,
  };
}
