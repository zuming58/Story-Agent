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
  // On slower Windows disks that can legitimately exceed Playwright's 5s
  // assertion default even though the request is still progressing.
  await expect(page).toHaveURL(/\/planning$/, { timeout: 15_000 });
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
  await page.getByRole("link", { name: /质量中心/ }).click();
  await expect(page.getByRole("heading", { name: "备份恢复与调用诊断" })).toBeVisible();
  await expect(page.getByRole("article", { name: "备份管理" })).toBeVisible();
  await expect(page.getByRole("article", { name: "审计时间线" })).toBeVisible();
  await expect(page.getByRole("article", { name: "模型调用记录" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();
});
