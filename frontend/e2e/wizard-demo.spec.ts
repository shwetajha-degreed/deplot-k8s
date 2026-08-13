import { test, expect } from "@playwright/test";

/**
 * Full Demo Mode regression — ship → watch → heal.
 * Requires backend on :8000 and frontend on :3000 (or Playwright webServer).
 */
test.describe("Demo wizard regression", () => {
  test("end-to-end platform → observability → AIOps self-heal", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("switch").click();
    await page.getByRole("button", { name: "Analyze Repository" }).click();
    await expect(page.getByRole("heading", { name: "Stack detected" })).toBeVisible();
    await expect(page.getByText("nextjs", { exact: true })).toBeVisible();

    await page.getByRole("button", { name: "View Architecture" }).click();
    await expect(page.getByRole("heading", { name: "Infrastructure architecture" })).toBeVisible();
    await expect(page.locator(".react-flow").first()).toBeVisible();

    await page.getByRole("button", { name: "Deployment Plan" }).click();
    await expect(page.getByRole("heading", { name: "Deployment plan" })).toBeVisible();
    await expect(page.getByText("Est. monthly cost")).toBeVisible();

    await page.getByRole("button", { name: "Generate Zerops Config" }).click();
    await expect(page.getByRole("heading", { name: "Zerops configuration" })).toBeVisible();
    await expect(page.getByText("import.yaml")).toBeVisible();
    await expect(page.getByText("Pre-deploy validation")).toBeVisible();
    await expect(page.getByText("MISSING_ENV")).toBeVisible();

    await page.getByRole("button", { name: "Deploy to Zerops" }).click();
    await expect(page.getByRole("heading", { name: "Deploying to Zerops" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Observability" })).toBeVisible({
      timeout: 45_000,
    });

    await page.getByRole("button", { name: "Open Observability" }).click();
    await expect(page.getByRole("heading", { name: "Observability" })).toBeVisible();
    await expect(page.getByText("Active incident detected")).toBeVisible();
    await expect(page.getByText("AI log summary")).toBeVisible();

    await page.getByRole("button", { name: /View Incident/i }).click();
    await expect(page.getByRole("heading", { name: "AIOps incidents" })).toBeVisible();
    await expect(page.getByText("Backend cannot start")).toBeVisible();
    await expect(page.getByText("Prisma migration failed")).toBeVisible();

    await page.getByRole("button", { name: "Apply AI Fix & Redeploy" }).click();
    await expect(page.getByText("Fix applied")).toBeVisible({ timeout: 20_000 });

    await page.getByRole("button", { name: "Deployment Score" }).click();
    await expect(page.getByRole("heading", { name: "Deployment score" })).toBeVisible();
    await expect(page.getByText("security", { exact: true })).toBeVisible();
  });
});
