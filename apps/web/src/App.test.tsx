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
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/projects")) return json([project]);
      if (url.includes("/plan")) return json(storyPlan);
      if (url.includes("/agent/sessions")) return json([{ id: "session-1", projectId: project.id, scope: ["第一卷"], status: "idle", messages: initialMessages }]);
      if (url.includes("/change-proposals")) return json([initialProposal]);
      if (url.includes("/audit-events")) return json([]);
      if (url.endsWith("/model-providers") && init?.method === "POST") return json({
        id: "provider-custom",
        name: "测试 Provider",
        providerType: "openai-compatible",
        baseUrl: "https://api.example.test",
        timeoutSeconds: 30,
        maxRetries: 1,
        isEnabled: true,
        hasApiKey: true,
        apiKeyPreview: "1234",
        createdAt: "2026-07-12T00:00:00Z",
        updatedAt: "2026-07-12T00:00:00Z",
      });
      if (url.endsWith("/model-providers")) return json([]);
      if (url.endsWith("/model-role-bindings")) return json([
        { role: "planner", modelId: null, model: null, dailyCostLimit: null, updatedAt: "2026-07-12T00:00:00Z" },
      ]);
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

  it("opens model settings and clears key input after save", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "模型与费用设置" })).toBeInTheDocument();
    const keyInput = screen.getByLabelText("新增 Provider API Key");
    await user.clear(screen.getByLabelText("新增 Provider 名称"));
    await user.type(screen.getByLabelText("新增 Provider 名称"), "测试 Provider");
    await user.clear(screen.getByLabelText("新增 Provider Base URL"));
    await user.type(screen.getByLabelText("新增 Provider Base URL"), "https://api.example.test");
    await user.type(keyInput, "unit-test-should-clear");
    await user.click(screen.getByRole("button", { name: /新增 Provider/ }));
    expect(await screen.findByText("Provider 已保存，密钥输入已清空。")).toBeInTheDocument();
    expect(keyInput).toHaveValue("");
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
  });
});
