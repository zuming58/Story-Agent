import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.goto("/planning");
  await page.evaluate(() => localStorage.clear());
  await page.reload();
});

test("review, accept and undo an AI planning change", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "故事规划中心" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "故事 Agent" })).toBeVisible();

  await page.getByRole("button", { name: /接受选中/ }).click();
  await expect(page.getByText("修改已应用，可随时撤销")).toBeVisible();
  await expect(page.getByLabel("目标章节")).toHaveValue("22");

  await page.getByRole("button", { name: /撤销/ }).click();
  await expect(page.getByLabel("目标章节")).toHaveValue("18");
});

test("direct edits are validated and persist after reload", async ({ page }) => {
  const target = page.getByLabel("目标章节");
  await target.fill("112");
  await expect(page.getByText(/目标章节必须位于 1—100 章/)).toBeVisible();
  await expect(page.getByRole("button", { name: /保存规划/ }).first()).toBeDisabled();

  await target.fill("19");
  await page.getByRole("button", { name: /保存规划/ }).first().click();
  await page.reload();
  await expect(page.getByLabel("目标章节")).toHaveValue("19");
});
