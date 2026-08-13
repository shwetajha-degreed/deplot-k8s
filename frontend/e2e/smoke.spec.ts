import { test, expect } from "@playwright/test";

test.describe("Smoke", () => {
  test("home page loads connect step", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "Connect your repository" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Analyze Repository" })).toBeEnabled();
  });

  test("dashboard mission control loads", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { name: "Platform dashboard" })).toBeVisible();
    await expect(page.getByRole("link", { name: "+ New deployment" })).toBeVisible();
  });
});
