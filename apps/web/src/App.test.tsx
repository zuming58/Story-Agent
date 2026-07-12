import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { App } from "./App";
import { initialMessages, initialProposal, project, storyPlan } from "./data/mockStory";

const json = (value: unknown) => Promise.resolve(new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }));

describe("Story Agent shell", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/projects")) return json([project]);
      if (url.includes("/plan")) return json(storyPlan);
      if (url.includes("/agent/sessions")) return json([{ id: "session-1", projectId: project.id, scope: ["第一卷"], status: "idle", messages: initialMessages }]);
      if (url.includes("/change-proposals")) return json([initialProposal]);
      if (url.includes("/audit-events")) return json([]);
      return json({ status: "ok" });
    }));
  });

  it("keeps the Agent panel while navigating between modules", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/planning"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "故事规划中心" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Canon/ }));
    expect(screen.getByRole("heading", { name: "Canon 设定库" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
  });
});
