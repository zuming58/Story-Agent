import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function createProject(page: Page, testInfo: TestInfo, suffix: string) {
  await page.goto("/overview");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByRole("button", { name: "新建作品" }).click();
  const title = `E2E-${testInfo.project.name}-${suffix}-${Date.now()}`;
  await page.getByLabel("作品名称").fill(title);
  await page.getByRole("button", { name: "创建作品" }).click();
  // Project creation initializes and migrates an isolated SQLite database.
  // A cold Windows filesystem/antivirus scan can take more than 15 seconds;
  // keep the test above the measured cold-start envelope so Playwright never
  // kills the API halfway through an Alembic migration.
  await expect(page).toHaveURL(/\/planning$/, { timeout: 45_000 });
  await expect(page.getByRole("heading", { name: "故事规划中心" })).toBeVisible();
  const projects = await (await page.request.get("/api/v1/projects")).json();
  return projects.find((project: { title: string }) => project.title === title) as { id: string; title: string };
}

async function seedProposal(page: Page, projectId: string) {
  const sessions = await (await page.request.get(`/api/v1/projects/${projectId}/agent/sessions`)).json();
  await page.request.post(`/api/v1/agent/sessions/${sessions[0].id}/messages`, {
    data: {
      projectId,
      content: "请调整当前里程碑节奏，并生成待确认修改提案。",
      selectedNodeId: "milestone-opening",
      action: "replan",
    },
  });
  await page.reload();
}

test("review, accept and undo an AI planning change", async ({ page }, testInfo) => {
  const project = await createProject(page, testInfo, "proposal");
  await seedProposal(page, project.id);
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();

  await expect(page.getByRole("region", { name: "AI 修改提案" })).toBeVisible();
  await page.getByRole("button", { name: /接受选中/ }).click();
  await expect(page.getByText("修改已应用并写入审计")).toBeVisible();
  await expect(page.getByLabel("目标章节")).toHaveValue("22");

  await page.getByRole("button", { name: "撤销" }).click();
  await expect(page.getByLabel("目标章节")).toHaveValue("1");
});

test("direct edits are validated and persist after reload", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "edit");
  const target = page.getByLabel("目标章节");
  await target.fill("112");
  await expect(page.locator(".validation-banner")).toBeVisible();
  await expect(page.getByRole("button", { name: /保存规划/ }).first()).toBeDisabled();

  await target.fill("3");
  await page.getByRole("button", { name: /保存规划/ }).first().click();
  await page.reload();
  await expect(page.getByLabel("目标章节")).toHaveValue("3");
});

test("safety audit workspace exposes backup and diagnostics without covering Agent", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "safety");
  await page.getByRole("link", { name: /模型设置/ }).click();
  await page.getByRole("button", { name: /安全审计/ }).click();
  await expect(page.getByRole("heading", { name: "备份恢复与调用诊断" })).toBeVisible();
  await expect(page.getByRole("article", { name: "备份管理" })).toBeVisible();
  await expect(page.getByRole("article", { name: "审计时间线" })).toBeVisible();
  await expect(page.getByRole("article", { name: "模型调用记录" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();
});

test("chapter workbench persists a locked contract and queued job", async ({ page }, testInfo) => {
  const project = await createProject(page, testInfo, "writing");
  const canon = await (await page.request.get(`/api/v1/projects/${project.id}/canon`)).json();
  const locked = await page.request.post(`/api/v1/projects/${project.id}/canon/lock`, { data: { expectedRevision: canon.documents[0].revision } });
  expect(locked.ok()).toBe(true);
  await page.getByRole("link", { name: /章节写作/ }).click();
  await expect(page.getByRole("heading", { name: "章节写作工作台" })).toBeVisible();
  await page.getByRole("button", { name: /生成章节契约/ }).click();
  await expect(page.getByText("DRAFT", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /校验并锁定/ }).click();
  await expect(page.getByText("LOCKED", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /创建写作任务/ }).first().click();
  await expect(page.getByRole("button", { name: /开始生成本章/ })).toBeVisible();
  await page.reload();
  await expect(page.getByText("LOCKED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /开始生成本章/ })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();
});

test("quality center remains usable at both desktop baselines", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "quality");
  await page.getByRole("link", { name: /质量中心/ }).click();
  await expect(page.getByRole("heading", { name: "章节质量中心" })).toBeVisible();
  await expect(page.getByText("综合质量门")).toBeVisible();
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

test("canon draft persists and locks behind explicit confirmation", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "canon");
  await page.getByRole("link", { name: /Canon/ }).click();
  await expect(page.getByRole("heading", { name: "Canon 设定库" })).toBeVisible();
  const editor = page.getByLabel("故事核心 Markdown");
  await editor.fill("# 雾城守夜人\n\n午夜后不可直视纸人，林默只能使用一张黄符。\n");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByRole("status")).toContainText("故事核心草稿已保存");
  await page.reload();
  await expect(editor).toHaveValue(/午夜后不可直视纸人/);
  await page.getByRole("button", { name: "锁定 Canon" }).click();
  await expect(page.getByRole("dialog")).toContainText("权威边界");
  await page.getByRole("button", { name: "确认锁定" }).click();
  await expect(page.getByText("正式 Canon 已锁定")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});

test("automation desk exposes trial sizes, blockers and persisted policy", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "automation");
  await page.getByRole("link", { name: /自动托管/ }).click();
  await expect(page.getByRole("heading", { name: "自动托管控制台" })).toBeVisible();
  await expect(page.getByRole("region", { name: "试写就绪检查" })).toBeVisible();
  await expect(page.getByText("每日托管策略")).toBeVisible();
  await page.getByLabel("运行时间").fill("07:35");
  await page.getByRole("button", { name: "保存策略" }).click();
  await expect(page.getByRole("status")).toContainText("托管策略已保存");
  await page.getByRole("button", { name: /短链路 3 章/ }).click();
  await expect(page.getByRole("button", { name: /开始第 1—3 章/ })).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("运行时间")).toHaveValue("07:35");
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
