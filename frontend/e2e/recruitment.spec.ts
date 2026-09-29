import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "Demo!Passw0rd123";
const ORG = process.env.E2E_ORG ?? "demo";

async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("Work e-mail").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Recruitment dashboard" })).toBeVisible();
}

test("unauthenticated users are redirected to login", async ({ page }) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard/);
});

test("candidate applies through the careers site", async ({ page }) => {
  await page.goto(`/careers/${ORG}`);
  await page.getByRole("link", { name: /Senior Backend Engineer/ }).click();
  const uid = Date.now();
  await page.getByLabel("First name").fill("Playwright");
  await page.getByLabel("Last name").fill(`Tester${uid}`);
  await page.getByLabel("E-mail").fill(`pw${uid}@example.com`);
  await page.getByLabel(/^CV/).setInputFiles({
    name: "cv.txt", mimeType: "text/plain",
    buffer: Buffer.from("Pat Tester\nBackend Engineer\nExperience\nEngineer at Acme  Jan 2017 - Present\nPython, PostgreSQL, AWS, Kafka\n"),
  });
  await page.getByLabel(/right to work/).selectOption("true");
  await page.getByLabel(/I consent to my data/).check();
  await page.getByRole("button", { name: "Submit application" }).click();
  await expect(page.getByText("Application received")).toBeVisible();
});

test("recruiter reviews AI screening evidence in the workspace", async ({ page }) => {
  await login(page, `recruiter@${ORG}.example.com`);
  await page.getByRole("link", { name: "AI screening" }).click();
  await expect(page.getByRole("heading", { name: "AI screening workspace" })).toBeVisible();
  await page.locator("tbody a").first().click();
  await expect(page.getByRole("heading", { name: "Facts from candidate material" })).toBeVisible();
  await expect(page.getByText(/waiting on/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Advance" })).toBeVisible();
});

test("staff navigation respects RBAC", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Work e-mail").fill(`interviewer@${ORG}.example.com`);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.waitForURL(/dashboard/);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Interviews" })).toBeVisible();
  await expect(nav.getByRole("link", { name: "Offers" })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Administration" })).toHaveCount(0);
});

test("analytics and agent monitoring render for HR", async ({ page }) => {
  await login(page, `hr.manager@${ORG}.example.com`);
  await page.getByRole("link", { name: "Analytics" }).click();
  await expect(page.getByText("Candidate pipeline (reached stage)")).toBeVisible();
  await page.getByRole("link", { name: "AI agents" }).click();
  await expect(page.getByRole("heading", { name: "AI agent monitoring" })).toBeVisible();
  await expect(page.getByRole("table").first().getByText("Candidate Screening Agent")).toBeVisible();
});
