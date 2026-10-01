/* Automated accessibility scan (axe-core, WCAG 2 A/AA) of the main screens. Serious/critical issues fail. */
import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

const collected: string[] = [];
test.afterAll(() => { if (collected.length) console.log("A11Y_SUMMARY\n" + collected.join("\n")); });
const email = `a11y-${Date.now()}@example.com`;

async function scan(page: Page, name: string) {
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).exclude(".react-flow__minimap").analyze();
  const bad = r.violations.filter((v) => ["serious", "critical"].includes(v.impact || ""));
  collected.push(...bad.map((v) => `${name} | ${v.id} | ${v.nodes.length} | ${v.nodes.slice(0, 4).map((x) => x.target.join(" ")).join(" ; ")}`));
  if (process.env.A11Y_REPORT_ONLY !== "1") expect(bad, `${name}: ${bad.map((v) => v.id).join(", ")}`).toEqual([]);
}

test("main screens have no serious accessibility violations", async ({ page }) => {
  await page.goto("/login");
  await scan(page, "login");
  await page.goto("/register");
  await page.fill("#name", "A"); await page.fill("#email", email); await page.fill("#pw", "correct-horse-battery");
  await page.click("button:has-text('Create account')");
  await page.waitForURL("**/dashboard**");
  await scan(page, "dashboard");
  await page.goto("/projects");
  await page.click("button:has-text('New project')"); await page.fill("#pn", "A11y"); await page.click("button:has-text('Create project')");
  await page.waitForURL(/\/projects\/[0-9a-f-]+$/);
  const project = page.url();
  await scan(page, "project");
  await page.click("button:has-text('New workflow')");
  await page.click("button:has-text('From a template')");
  await page.click("button:has-text('Company Research')");
  await page.selectOption("select[aria-label=Provider]", "local_test");
  await page.locator("select[aria-label=Model] option[value=echo]").waitFor({ state: "attached" });
  await page.selectOption("select[aria-label=Model]", "echo");
  await page.click("button:has-text('Use template')");
  await page.waitForURL("**/workflows/**");
  await page.waitForSelector(".react-flow__node");
  await scan(page, "builder");
  await page.locator(".react-flow__node", { hasText: "Summarizer" }).click();
  await scan(page, "builder-inspector");
  for (const [path, name] of [["/agents", "agents"], ["/templates", "templates"], ["/policies", "policies"], ["/models", "models"], ["/integrations", "integrations"], ["/settings", "settings"],
    [`${project}?tab=triggers`, "triggers"], [`${project}?tab=monitoring`, "monitoring"]]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    await scan(page, name);
  }
});
