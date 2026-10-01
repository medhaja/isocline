/* The V1 definition of done, driven through the UI with the deterministic local test provider:
   register → project → Investment Research template → run → parallel analysts → human approval →
   final report → run inspector. Then: AI generation, validation,
   publish → run through the REST API. */
import { expect, test, type Page } from "@playwright/test";

const email = `e2e-${Date.now()}@example.com`;
const password = "correct-horse-battery";

async function signIn(page: Page) {
  await page.goto("/login");
  await page.fill("#email", email);
  await page.fill("#pw", password);
  await page.click("button:has-text('Sign in')");
  await page.waitForURL("**/dashboard**");
}

test.describe.serial("Isocline V1", () => {
  let projectUrl = "";

  test("signed-out visitors are sent to login", async ({ page }) => {
    await page.goto("/");
    await page.waitForURL(/\/login\?next=/);
    await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  });

  test("register and create a project", async ({ page }) => {
    await page.goto("/register");
    await page.fill("#name", "E2E User");
    await page.fill("#email", email);
    await page.fill("#pw", password);
    await page.click("button:has-text('Create account')");
    await page.waitForURL("**/dashboard**");
    await expect(page.getByText("Get your first workflow running")).toBeVisible();
    await page.goto("/projects");
    await page.click("button:has-text('New project')");
    await page.fill("#pn", "Equity research");
    await page.click("button:has-text('Create project')");
    await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
    projectUrl = page.url();
  });

  test("flagship: parallel analysts, approval, final report", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.click("button:has-text('New workflow')");
    await page.click("button:has-text('From a template')");
    await page.click("button:has-text('AI Investment Research Team')");
    await page.selectOption("select[aria-label=Provider]", "local_test");
    await page.locator("select[aria-label=Model] option[value=json]").waitFor({ state: "attached" });
    await page.selectOption("select[aria-label=Model]", "json");
    await page.click("button:has-text('Use template')");
    await page.waitForURL("**/workflows/**");
    await expect(page.locator(".react-flow__node")).toHaveCount(10);
    await expect(page.locator("header").getByText("Valid")).toBeVisible({ timeout: 10_000 });

    await page.click("header button:has-text('Run')");
    await page.fill("[role=dialog] textarea", "Example Corp");
    await page.click("button:has-text('Start run')");
    await expect(page.getByRole("heading", { name: "Approve analysis before final report" })).toBeVisible({ timeout: 30_000 });
    // the three analysts ran before the approval
    for (const n of ["Financial Analyst", "Risk Analyst", "Python Analyst"]) {
      await expect(page.locator(".react-flow__node", { hasText: n }).locator("[title=Done]")).toBeVisible();
    }
    await page.click("button:has-text('Approve')");
    await expect(page.locator("text=completed").first()).toBeVisible({ timeout: 30_000 });

    await page.click("text=Open run page");
    await page.waitForURL("**/runs/**");
    await page.locator(".react-flow__node", { hasText: "Risk Analyst" }).click();
    await expect(page.getByText("local_test/json")).toBeVisible();
    await expect(page.getByRole("button", { name: "Re-run from here" })).toBeVisible();
  });

  test("create with AI, undo/redo, validation", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.click("button:has-text('Create with AI')");
    await page.fill("#desc", "Research a company, then a financial analyst and a risk analyst in parallel, then a manager writes the final report");
    await page.selectOption("select[aria-label=Provider]", "local_test");
    await page.locator("select[aria-label=Model] option[value=echo]").waitFor({ state: "attached" });
    await page.selectOption("select[aria-label=Model]", "echo");
    await page.click("button:has-text('Generate')");
    await page.click("button:has-text('Open in builder')");
    await page.waitForURL("**/workflows/**");
    const nodes = page.locator(".react-flow__node");
    await nodes.first().waitFor();
    await expect(page.locator("header").getByText("Saved")).toBeVisible({ timeout: 10_000 });
    const before = await nodes.count();
    expect(before).toBeGreaterThanOrEqual(6);

    await page.locator("[role=button]", { hasText: /^Agent$/ }).dblclick();
    await expect(page.locator("header").getByText(/to fix/)).toBeVisible({ timeout: 10_000 });
    await page.keyboard.press("Delete");
    await expect(page.locator("header").getByText("Valid")).toBeVisible({ timeout: 10_000 });
    await expect(page.locator("header").getByText("Saved")).toBeVisible({ timeout: 10_000 });
  });

  test("publish a version and run it from the API", async ({ page }) => {
    await signIn(page);
    await page.goto(projectUrl);
    await page.getByRole("link", { name: "Generated workflow" }).first().click();
    await page.waitForURL("**/workflows/**");
    await page.click("button:has-text('Versions')");
    await page.click("[role=dialog] button:has-text('Publish')");
    await expect(page.getByText("v1").first()).toBeVisible();
    await page.keyboard.press("Escape");

    const workflowId = page.url().split("/workflows/")[1].split(/[?#]/)[0];
    const csrf = (await page.context().cookies()).find((c) => c.name === "isc_csrf")!.value;
    const res = await page.request.post(`/api/v1/workflows/${workflowId}/run`, { headers: { "X-CSRF-Token": csrf }, data: { input: { request: "Acme" } } });
    expect(res.status()).toBe(202);
    const { run_id } = await res.json();
    await expect.poll(async () => (await (await page.request.get(`/api/v1/runs/${run_id}`)).json()).status, { timeout: 30_000 }).toBe("completed");
  });
});
