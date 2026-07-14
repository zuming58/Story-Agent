import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import { App } from "./App";
import { initialMessages, initialProposal, project, storyPlan } from "./data/mockStory";

const json = (value: unknown) => Promise.resolve(new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }));
const stream = (events: unknown[]) => Promise.resolve(new Response(events.map((event) => `event: ${(event as { event: string }).event}\ndata: ${JSON.stringify(event)}\n\n`).join(""), { status: 200, headers: { "Content-Type": "text/event-stream" } }));
const canonMock = {
  projectId: project.id, locked: false,
  documents: [{ id: "story-core", title: "夜巡人 Story Core", kind: "story-core", contentMarkdown: "# 夜巡人\n\n雾城存在夜巡规则。", status: "draft", revision: 1, lockedAt: null }],
  entityTypes: [{ id: "type-person", name: "person", displayName: "人物", schemaJson: { type: "object" }, isSystem: true, status: "draft", revision: 1, sourceDocumentId: "story-core", lockedAt: null }],
  entities: [{ id: "entity-lin", entityTypeId: "type-person", canonicalName: "林默", aliases: ["小林"], attributes: { role: "夜巡人" }, status: "draft", revision: 1, sourceDocumentId: "story-core", lockedAt: null }],
  relations: [],
  rules: [{ id: "rule-night", ruleCode: "NIGHT-001", category: "world", statement: "午夜后不能直视纸人。", severity: "high", constraintJson: {}, status: "draft", revision: 1, sourceDocumentId: "story-core", lockedAt: null }],
  changeRequests: [],
};
const readinessMock = {
  projectId: project.id, chapterCount: 1, startChapter: 37, endChapter: 37, ready: false, maxSafeChapterCount: 0,
  checks: [
    { code: "TRIAL_MODELS_READY", status: "ready", title: "写作模型已就绪", detail: "角色均可用。", actionPath: "/settings", chapterNumber: null },
    { code: "TRIAL_CANON_NOT_LOCKED", status: "blocked", title: "Canon 尚未锁定", detail: "请检查后锁定。", actionPath: "/canon", chapterNumber: null },
  ],
};
const policyMock = {
  projectId: project.id, enabled: false, timeOfDay: "06:00", timezone: "Asia/Shanghai", chaptersPerRun: 1,
  targetWordsMin: 2200, targetWordsMax: 3200, maxRevisionRounds: 2, dailyCostLimit: null,
  stopPolicy: "stop_on_blocking", approvalMode: "guarded_auto", nextRunAt: null, lastScheduledLocalDate: null,
  revision: 1, createdAt: "2026-07-12T00:00:00Z", updatedAt: "2026-07-12T00:00:00Z",
};

describe("Story Agent shell", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/projects")) return json([project]);
      if (url.includes("/plan")) return json(storyPlan);
      if (url.includes("/messages/stream")) return stream([
        { event: "run_started", runId: "run-1", provider: "测试 Provider", model: "fake-planner", requestId: "req-1" },
        { event: "text_delta", runId: "run-1", delta: "流式回答" },
        { event: "completed", runId: "run-1", message: { id: "message-stream", role: "assistant", content: "流式回答", timestamp: "2026-07-12T00:00:00Z" } },
      ]);
      if (url.includes("/agent/sessions")) return json([{ id: "session-1", projectId: project.id, scope: ["第一卷"], status: "idle", messages: initialMessages }]);
      if (url.includes("/change-proposals")) return json([initialProposal]);
      if (url.includes("/audit-events")) return json([]);
      if (url.includes("/model-runs")) return json([]);
      if (url.includes("/trial-readiness")) return json(readinessMock);
      if (url.includes("/canon")) return json(canonMock);
      if (url.includes("/automation/policy")) return json(policyMock);
      if (url.includes("/automation/runs")) return json([]);
      if (url.includes("/automation/reports")) return json([]);
      if (url.includes("/chapter-contracts")) return json([]);
      if (url.includes("/chapter-jobs")) return json([]);
      if (url.includes("/chapters/") && url.endsWith("/drafts")) return json([]);
      if (url.includes("/chapters/") && url.endsWith("/commits")) return json([]);
      if (url.includes("/backups") && init?.method === "POST") return json({
        backupId: "backup-1",
        projectId: project.id,
        projectTitle: project.title,
        createdAt: "2026-07-12T00:00:00Z",
        files: { "story.db": "hash" },
        archivePath: "F:/tmp/backup.zip",
      });
      if (url.includes("/backups")) return json([]);
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

  it("streams Agent replies with model run status", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/planning"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "故事规划中心" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("给故事 Agent 发送消息"), "检查一下节奏");
    await user.click(screen.getByRole("button", { name: "发送" }));
    expect(await screen.findByText("流式回答")).toBeInTheDocument();
    expect(screen.getAllByText(/测试 Provider \/ fake-planner/).length).toBeGreaterThan(0);
    expect(screen.getByRole("region", { name: "模型运行状态" })).toBeInTheDocument();
  });

  it("opens the safety audit workspace with backup and diagnostics panels", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/settings"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    await user.click(await screen.findByRole("button", { name: /安全审计/ }));
    expect(await screen.findByRole("heading", { name: "备份恢复与调用诊断" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "备份管理" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "审计时间线" })).toBeInTheDocument();
    expect(screen.getByRole("article", { name: "模型调用记录" })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
  });

  it("opens the real chapter writing and quality workspaces", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/writing"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "章节写作工作台" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /生成章节契约/ })).toBeInTheDocument();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /质量中心/ }));
    expect(await screen.findByRole("heading", { name: "章节质量中心" })).toBeInTheDocument();
    expect(screen.getByText("综合质量门")).toBeInTheDocument();
  });

  it("opens the real automation desk with persisted policy and readiness", async () => {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/automation"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    expect(await screen.findByRole("heading", { name: "自动托管控制台" })).toBeInTheDocument();
    expect(await screen.findByText("每日托管策略")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "试写就绪检查" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /开始第 37—37 章/ })).toBeDisabled();
    expect(screen.getByRole("complementary", { name: "故事 Agent" })).toBeInTheDocument();
  });

  it("saves the Canon story core as a database-backed draft", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={queryClient}><TooltipProvider><MemoryRouter initialEntries={["/canon"]}><App /></MemoryRouter></TooltipProvider></QueryClientProvider>);

    const editor = await screen.findByLabelText("故事核心 Markdown");
    await user.type(editor, "\n新增能力边界。");
    await user.click(screen.getByRole("button", { name: /保存草稿/ }));
    expect(await screen.findByText("故事核心草稿已保存。")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url, init]) => String(url).includes("/canon/draft") && init?.method === "PUT")).toBe(true);

    await user.type(screen.getByLabelText("给故事 Agent 发送消息"), "检查当前设定");
    await user.click(screen.getByRole("button", { name: "发送" }));
    const streamCall = vi.mocked(fetch).mock.calls.find(([url]) => String(url).includes("/messages/stream"));
    expect(streamCall).toBeDefined();
    const payload = JSON.parse(String(streamCall?.[1]?.body)) as { content: string; selectedNodeId?: string };
    expect(payload.content).toContain("Canon 设定库");
    expect(payload.selectedNodeId).toBeUndefined();
  });
});
