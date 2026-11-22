import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { installMockApi } from "./fixtures/mockApi";

const WCAG_21_AA_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function runAxeAudit(
  page: Page,
  testInfo: TestInfo,
  label: string,
  includeSelector?: string
) {
  let builder = new AxeBuilder({ page }).withTags(WCAG_21_AA_TAGS);
  if (includeSelector) {
    builder = builder.include(includeSelector);
  }
  const results = await builder.analyze();

  await testInfo.attach(`axe-${label}`, {
    body: JSON.stringify(
      {
        label,
        url: results.url,
        timestamp: results.timestamp,
        passesCount: results.passes.length,
        incompleteCount: results.incomplete.length,
        violationsCount: results.violations.length,
        violations: results.violations.map((v) => ({
          id: v.id,
          impact: v.impact,
          help: v.help,
          helpUrl: v.helpUrl,
          nodesCount: v.nodes.length,
          targets: v.nodes.slice(0, 5).map((n) => n.target),
        })),
      },
      null,
      2
    ),
    contentType: "application/json",
  });

  console.log(
    `[axe-core:${label}] passes=${results.passes.length} incomplete=${results.incomplete.length} violations=${results.violations.length}`
  );
  for (const violation of results.violations) {
    console.log(
      `[axe-core:${label} violation] id=${violation.id} impact=${violation.impact} nodes=${violation.nodes.length} help="${violation.help}" targets=${JSON.stringify(violation.nodes.slice(0, 3).map((n) => n.target))}`
    );
  }

  return results;
}

async function loadReadyDashboard(page: Page) {
  await installMockApi(page);
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
  ).toBeVisible();
  await expect(
    page.locator("#section-summary").getByText("78").first()
  ).toBeVisible();
  await expect(
    page.locator("#section-intelligence").getByText(/Peak Forecast Risk/i).first()
  ).toBeVisible();
  await expect(
    page
      .locator("#section-history")
      .getByRole("heading", { name: /Daily US AQI Trend/i })
  ).toBeVisible();
  await expect(
    page
      .locator("#section-assistant")
      .getByText(/Gemini Ready \(gemini-2\.5-flash\)/i)
  ).toBeVisible();
}

test.describe("AIRWISE AI Accessibility Automation & Validation (Phase 8 Step 4)", () => {
  test.describe.configure({ timeout: 60_000 });

  test("passes WCAG 2.1 A/AA axe-core scan on primary Live Model dashboard (desktop 1280x800)", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await loadReadyDashboard(page);

    const results = await runAxeAudit(page, testInfo, "live-desktop-1280");
    expect(results.violations).toEqual([]);
  });

  test("passes WCAG 2.1 A/AA axe-core scans on Historical Hourly and 4-City Comparison chart states", async ({
    page,
  }, testInfo) => {
    await loadReadyDashboard(page);
    const historySection = page.locator("#section-history");

    // 1. Switch to 7-day Hourly chart and scan
    await historySection
      .getByRole("button", { name: /Hourly \(7d only\)/i })
      .click();
    await expect(
      historySection.getByRole("heading", { name: /7-Day Hourly US AQI Trend/i })
    ).toBeVisible();

    const hourlyResults = await runAxeAudit(
      page,
      testInfo,
      "history-hourly",
      "#section-history"
    );
    expect(hourlyResults.violations).toEqual([]);

    // 2. Switch to 4-City Comparison tab and scan
    await historySection
      .getByRole("tab", { name: /4-City Comparison/i })
      .click();
    await expect(
      historySection.getByRole("heading", {
        name: /Four-City Daily Average US AQI Comparison/i,
      })
    ).toBeVisible();

    const compareResults = await runAxeAudit(
      page,
      testInfo,
      "history-compare",
      "#section-history"
    );
    expect(compareResults.violations).toEqual([]);
  });

  test("passes WCAG 2.1 A/AA axe-core scan in Demo Mode and with Assistant response rendered", async ({
    page,
  }, testInfo) => {
    await loadReadyDashboard(page);

    // 1. Render an Assistant city-comparison response and scan #section-assistant
    const assistantSection = page.locator("#section-assistant");
    await assistantSection
      .getByRole("button", { name: "Compare all 4 cities" })
      .click();
    await expect(
      assistantSection.getByText(/Verified 4-City Model Comparison Snapshot/i)
    ).toBeVisible();

    const assistantResults = await runAxeAudit(
      page,
      testInfo,
      "assistant-response",
      "#section-assistant"
    );
    expect(assistantResults.violations).toEqual([]);

    // 2. Activate Demo Mode and scan full page
    const banner = page.getByRole("region", {
      name: /Environmental data provenance disclosure notice/i,
    });
    await banner.getByRole("button", { name: /Use Demo Data Mode/i }).click();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();

    const demoResults = await runAxeAudit(page, testInfo, "demo-mode-full");
    expect(demoResults.violations).toEqual([]);
  });

  test("passes WCAG 2.1 A/AA axe-core scan at mobile (375x812) viewport", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await loadReadyDashboard(page);
    const results = await runAxeAudit(page, testInfo, "mobile-375");
    expect(results.violations).toEqual([]);
  });

  test("passes WCAG 2.1 A/AA axe-core scan at tablet (768x1024) viewport", async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await loadReadyDashboard(page);
    const results = await runAxeAudit(page, testInfo, "tablet-768");
    expect(results.violations).toEqual([]);
  });

  test("validates keyboard semantics and interaction for Map City List and Historical SVG charts", async ({
    page,
  }) => {
    await loadReadyDashboard(page);

    // 1. Map Configured Cities list: semantic <ul> -> <li> -> <button aria-pressed>
    const mapSection = page.locator("#section-map");
    const cityList = mapSection.getByRole("list", {
      name: /Configured African cities air quality status/i,
    });
    await expect(cityList.getByRole("listitem")).toHaveCount(4);

    const lagosBtn = cityList.getByRole("button", { name: /Lagos, Nigeria/i });
    const nairobiBtn = cityList.getByRole("button", {
      name: /Nairobi, Kenya/i,
    });
    await expect(lagosBtn).toHaveAttribute("aria-pressed", "true");
    await expect(nairobiBtn).toHaveAttribute("aria-pressed", "false");

    // Keyboard focus + Enter selects Nairobi and updates aria-pressed & dashboard heading
    await nairobiBtn.focus();
    await expect(nairobiBtn).toBeFocused();
    await page.keyboard.press("Enter");

    await expect(nairobiBtn).toHaveAttribute("aria-pressed", "true");
    await expect(lagosBtn).toHaveAttribute("aria-pressed", "false");
    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();

    // 2. Historical Daily SVG chart: role="group" + keyboard-focusable point buttons
    const historySection = page.locator("#section-history");
    const dailySvg = historySection.locator('svg[role="group"]').first();
    await expect(dailySvg).toBeVisible();
    await expect(dailySvg).toHaveAttribute(
      "aria-label",
      /Daily US AQI historical line chart/i
    );

    const firstDailyPoint = dailySvg
      .locator('circle[role="button"][tabindex="0"]')
      .first();
    await firstDailyPoint.focus();
    await expect(firstDailyPoint).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      historySection.getByRole("status").getByText("2026-11-14")
    ).toBeVisible();

    // 3. Historical Hourly SVG chart: role="group" + keyboard focusable point
    await historySection
      .getByRole("button", { name: /Hourly \(7d only\)/i })
      .click();
    const hourlySvg = historySection.locator('svg[role="group"]').first();
    await expect(hourlySvg).toBeVisible();
    const firstHourlyPoint = hourlySvg
      .locator('circle[role="button"][tabindex="0"]')
      .first();
    await firstHourlyPoint.focus();
    await expect(firstHourlyPoint).toBeFocused();
    await page.keyboard.press("Space");
    await expect(
      historySection.getByRole("status").getByText(/2026-11-20T00:00/i)
    ).toBeVisible();

    // 4. Historical 4-City Comparison SVG chart: role="group" + keyboard focusable point
    await historySection
      .getByRole("tab", { name: /4-City Comparison/i })
      .click();
    const compareSvg = historySection.locator('svg[role="group"]').first();
    await expect(compareSvg).toBeVisible();
    const firstComparePoint = compareSvg
      .locator('g[role="button"][tabindex="0"]')
      .first();
    await firstComparePoint.focus();
    await expect(firstComparePoint).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(
      historySection.getByRole("status").getByText(/Date: 2026-11-14/i)
    ).toBeVisible();
  });
});
