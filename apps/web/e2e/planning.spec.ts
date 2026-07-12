import { expect, test, type Page, type TestInfo } from "@playwright/test";

async function createProject(page: Page, testInfo: TestInfo, suffix: string) {
  await page.goto("/overview");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
  await page.getByRole("button", { name: "新建作品" }).click();
  await page.getByLabel("作品名称").fill(`E2E-${testInfo.project.name}-${suffix}-${Date.now()}`);
  await page.getByRole("button", { name: "创建作品" }).click();
  await expect(page).toHaveURL(/\/planning$/);
  await expect(page.getByRole("heading", { name: "故事规划中心" })).toBeVisible();
}

test("review, accept and undo an AI planning change", async ({ page }, testInfo) => {
  await createProject(page, testInfo, "proposal");
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();

  await page.getByRole("button", { name: "重排节奏" }).click();
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
