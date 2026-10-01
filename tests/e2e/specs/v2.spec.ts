/* V2 harness flows through the UI: preflight plan, contract/context/harness inspector, heatmap, optimizer,
   versions, run harness records, policies, governance pages. */
import { expect, test, type Page } from "@playwright/test";

const email = `v2-${Date.now()}@example.com`;
const password = "correct-horse-battery";
let projectUrl = "";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.fill("#email", email);
  await page.fill("#pw", password);
  await page.click("button:has-text('Sign in')");
  await page.waitForURL("**/dashboard**");
}

test.describe.serial("Isocline V2 harness", () => {
  test("setup: account, project, workflow from template", async ({ page }) => {
    await page.goto("/register");
    await page.fill("#name", "V2 User"); await page.fill("#email", email); await page.fill("#pw", password);
    await page.click("button:has-text('Create account')");
    await page.waitForURL("**/dashboard**");
    await page.goto("/projects");
    await page.click("button:has-text('New project')"); await page.fill("#pn", "Harness"); await page.click("button:has-text('Create project')");
    await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
    projectUrl = page.url();
    await page.click("button:has-text('New workflow')");
    await page.click("button:has-text('From a template')");
    await page.click("button:has-text('Company Research')");
    await page.selectOption("select[aria-label=Provider]", "local_test");
    await page.locator("select[aria-label=Model] option[value=echo]").waitFor({ state: "attached" });
    await page.selectOption("select[aria-label=Model]", "echo");
    await page.click("button:has-text('Use template')");
    await page.waitForURL("**/workflows/**");
    await expect(page.locator(".react-flow__node")).toHaveCount(4);
  });

  test("run dialog shows the execution plan and preflight", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.getByRole("link", { name: "Company Research" }).click();
    await page.waitForURL("**/workflows/**");
    await page.click("header button:has-text('Run')");
    await expect(page.getByText("Ready to run")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("Model calls").first()).toBeVisible();
    await page.fill("[role=dialog] textarea", "Acme");
    await page.click("button:has-text('Start run')");
    await expect(page.locator("text=completed").first()).toBeVisible({ timeout: 30_000 });
  });

  test("inspector: contract, context preview, harness, heatmap, optimizer", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.getByRole("link", { name: "Company Research" }).click();
    await page.locator(".react-flow__node", { hasText: "Summarizer" }).click();
    const design = page.locator("aside button:has-text('Design')");
    if (await design.count()) await design.click();
    await page.click("[role=tab]:has-text('Contract')");
    await page.click("button:has-text('Add a contract')");
    await page.selectOption("select[aria-label='Output type']", "Text");
    await expect(page.locator(".react-flow__node", { hasText: "Summarizer" }).getByText("Text")).toBeVisible();
    await page.click("[role=tab]:has-text('Context')");
    await expect(page.getByText("Model context preview")).toBeVisible();
    await expect(page.getByText("Estimated total")).toBeVisible({ timeout: 15_000 });
    await page.click("[role=tab]:has-text('Harness')");
    await page.click("button:has-text('exact')");
    await expect(page.getByText("Reuses a result only when")).toBeVisible();
    await page.keyboard.press("Escape");
    await page.click("header button:has-text('Heatmap')");
    await expect(page.getByText(/Heatmap · last/)).toBeVisible();
    await page.click("header button:has-text('Heatmap')");
    await page.click("header button:has-text('Optimize')");
    await page.click("button:has-text('Analyze workflow')");
    await expect(page.getByText("Cost / run")).toBeVisible({ timeout: 15_000 });
    await expect(page.locator("header").getByText("Saved")).toBeVisible({ timeout: 10_000 });
  });

  test("publish a version; run harness and lineage tabs", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.getByRole("link", { name: "Company Research" }).click();
    await page.click("header button:has-text('Versions')");
    await page.click("[role=dialog] button:has-text('Publish')");
    await expect(page.getByText("v1").first()).toBeVisible();
    await page.keyboard.press("Escape");
    await page.goto(projectUrl + "?tab=runs");
    await page.locator("table a").first().click();
    await page.waitForURL("**/runs/**");
    await page.click("[role=tab]:has-text('Harness')");
    await expect(page.getByText("Execution plan (at start)")).toBeVisible();
    await page.click("[role=tab]:has-text('Lineage')");
    await expect(page.getByText("Lineage shows recorded provenance only", { exact: false })).toBeVisible();
  });

  test("policies and governance pages", async ({ page }) => {
    await signIn(page);
    await page.goto("/policies");
    await page.click("button:has-text('New policy')");
    await page.fill("[role=dialog] input >> nth=0", "Production policy");
    await page.click("[role=dialog] button:has-text('Save policy')");
    await expect(page.getByText("require approval any tool (external write)")).toBeVisible();
    for (const [path, text] of [["/models", "capability registry"], ["/integrations", "MCP servers"], ["/monitoring", "Open alerts"], ["/settings", "Access tokens"]]) {
      await page.goto(path);
      await expect(page.getByText(text, { exact: false }).first()).toBeVisible();
    }
    for (const tab of ["triggers", "artifacts", "experiments", "monitoring"]) {
      await page.goto(`${projectUrl}?tab=${tab}`);
      await expect(page.locator("main")).not.toContainText("Something went wrong");
    }
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog", { name: "Command palette" })).toBeVisible();
  });
});
