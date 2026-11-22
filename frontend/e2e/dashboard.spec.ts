import { expect, test } from "@playwright/test";
import { installMockApi } from "./fixtures/mockApi";

test.describe("AIRWISE AI Dashboard Smoke & Initialization (A)", () => {
  test("renders main dashboard sections with deterministic mocked APIs", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => {
      pageErrors.push(error.message);
    });

    await installMockApi(page);
    await page.goto("/");

    // Primary dashboard heading & default location (Lagos)
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.getByText("lagos-ng").first()).toBeVisible();

    // Mocked AQI summary (78, Moderate)
    const summarySection = page.locator("#section-summary");
    await expect(summarySection).toBeVisible();
    await expect(summarySection.getByText("78").first()).toBeVisible();
    await expect(summarySection.getByText("Moderate").first()).toBeVisible();

    // All 5 pollutant cards
    const pollutantsSection = page.locator("#section-pollutants");
    await expect(pollutantsSection).toBeVisible();
    for (const code of ["PM2.5", "PM10", "NO2", "O3", "SO2"]) {
      await expect(
        pollutantsSection.getByRole("article", {
          name: new RegExp(`${code} measurement card`, "i"),
        })
      ).toBeVisible();
    }

    // Future hourly forecast section
    const forecastSection = page.locator("#section-forecast");
    await expect(forecastSection).toBeVisible();
    await expect(forecastSection.getByText(/24 hrs/i)).toBeVisible();

    // Predictive Risk Intelligence & Activity Planner section (Phase 7)
    const intelligenceSection = page.locator("#section-intelligence");
    await expect(intelligenceSection).toBeVisible();
    await expect(
      intelligenceSection.getByRole("heading", {
        name: /Predictive Risk Intelligence & Activity Planner/i,
      })
    ).toBeVisible();
    await expect(
      intelligenceSection.getByText(/Peak Forecast Risk/i).first()
    ).toBeVisible();
    await expect(
      intelligenceSection.getByRole("heading", {
        name: /Comparative Activity Planning/i,
      })
    ).toBeVisible();

    // Historical Trends section (Phase 6.2)
    await expect(
      page.getByRole("heading", {
        name: /Historical Air Quality Trends & Insights/i,
      })
    ).toBeVisible();

    // Model provenance & disclosure information
    const provenanceSection = page.locator("#section-provenance");
    await expect(provenanceSection).toBeVisible();
    await expect(
      provenanceSection.getByText(/Not Physical Roadside Sensor Telemetry/i)
    ).toBeVisible();
    await expect(
      provenanceSection.getByText(/Open-Meteo\.com/i).first()
    ).toBeVisible();

    expect(pageErrors).toEqual([]);
  });
});

test.describe("Location Selection (B)", () => {
  test("switches across all 4 canonical cities via dropdown and quick buttons without stale content", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const mockApi = await installMockApi(page);
    await page.goto("/");

    // Confirm initial Lagos load
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("78").first()).toBeVisible();

    // 1. Switch to Abuja via dropdown
    mockApi.clearRequests();
    const dropdown = page.getByLabel(/Monitored Urban Location/i);
    await dropdown.selectOption("abuja-ng");

    await expect(
      page.getByRole("heading", { name: /Abuja, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("62").first()).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Predictive Risk Intelligence & Activity Planner — Abuja, Nigeria/i,
      })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Historical Air Quality Trends & Insights — Abuja, Nigeria/i,
      })
    ).toBeVisible();

    // Verify API calls used canonical location_id=abuja-ng
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/intelligence") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/history") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);

    // 2. Switch to Nairobi via dropdown
    mockApi.clearRequests();
    await dropdown.selectOption("nairobi-ke");

    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("44").first()).toBeVisible();
    await expect(
      page.locator("#section-summary").getByText("Good").first()
    ).toBeVisible();

    // 3. Switch to Accra via quick city button
    mockApi.clearRequests();
    const quickSwitcher = page.getByRole("group", {
      name: /Quick urban location switcher/i,
    });
    await quickSwitcher.getByRole("button", { name: "Accra, Ghana" }).click();

    await expect(
      page.getByRole("heading", { name: /Accra, Ghana Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(
      quickSwitcher.getByRole("button", { name: "Accra, Ghana" })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(page.locator("#section-summary").getByText("56").first()).toBeVisible();
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality") &&
          r.searchParams.location_id === "accra-gh"
      )
    ).toBe(true);

    // 4. Switch back to Lagos via quick city button
    await quickSwitcher.getByRole("button", { name: "Lagos, Nigeria" }).click();
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("78").first()).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Accra, Ghana Air Quality Dashboard/i })
    ).toHaveCount(0);

    expect(pageErrors).toEqual([]);
  });

  test("prevents stale previous-city response from overwriting newer selection", async ({
    page,
  }) => {
    await installMockApi(page, {
      overrides: {
        airQuality: (url) => {
          // Make Abuja slow and Nairobi fast so switching Abuja -> Nairobi tests race protection
          if (url.searchParams.get("location_id") === "abuja-ng") {
            return { delayMs: 600 };
          }
          return { delayMs: 20 };
        },
      },
    });
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();

    const quickSwitcher = page.getByRole("group", {
      name: /Quick urban location switcher/i,
    });
    await quickSwitcher.getByRole("button", { name: "Abuja, Nigeria" }).click();
    await quickSwitcher.getByRole("button", { name: "Nairobi, Kenya" }).click();

    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("44").first()).toBeVisible();

    // Wait past the delayed Abuja response window and verify Nairobi stays current
    await page.waitForTimeout(750);
    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(page.locator("#section-summary").getByText("44").first()).toBeVisible();
  });
});

test.describe("Sidebar & Keyboard Navigation (C)", () => {
  test("navigates sections via sidebar links, keyboard input, and skip-to-content link", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await installMockApi(page);
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();

    // Skip-to-content link is first focusable element and targets #main-dashboard
    const skipLink = page.getByRole("link", {
      name: /Skip to main dashboard content/i,
    });
    await expect(skipLink).toHaveAttribute("href", "#main-dashboard");
    await skipLink.focus();
    await expect(skipLink).toBeFocused();

    // Verify all 10 actual sidebar navigation items exist
    const sidebarNav = page.getByRole("navigation", {
      name: /Dashboard sections/i,
    });
    const expectedNavItems: Array<{ label: string; href: string }> = [
      { label: "AQI Summary", href: "#section-summary" },
      { label: "Intelligence Map", href: "#section-map" },
      { label: "Pollutant Cards (5)", href: "#section-pollutants" },
      { label: "Hourly Forecast", href: "#section-forecast" },
      { label: "Risk Intelligence", href: "#section-intelligence" },
      { label: "Historical Trends", href: "#section-history" },
      { label: "Model Provenance", href: "#section-provenance" },
      { label: "Health Advisory", href: "#section-advisory" },
      { label: "Daily Planning", href: "#section-recommendations" },
      { label: "AIRWISE AI Assistant", href: "#section-assistant" },
    ];

    for (const item of expectedNavItems) {
      const link = sidebarNav.getByRole("link", { name: item.label });
      await expect(link).toBeVisible();
      await expect(link).toHaveAttribute("href", item.href);
    }

    // Click Risk Intelligence and verify URL hash, aria-current, and state preservation
    const intelligenceLink = sidebarNav.getByRole("link", {
      name: "Risk Intelligence",
    });
    await intelligenceLink.click();
    await expect(page).toHaveURL(/#section-intelligence$/);
    await expect(intelligenceLink).toHaveAttribute("aria-current", "true");
    await expect(page.locator("#section-intelligence")).toBeVisible();

    // Keyboard activation (Enter) on Historical Trends link
    const historyLink = sidebarNav.getByRole("link", {
      name: "Historical Trends",
    });
    await historyLink.focus();
    await expect(historyLink).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#section-history$/);
    await expect(historyLink).toHaveAttribute("aria-current", "true");

    // Dashboard state remains intact
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    expect(pageErrors).toEqual([]);
  });
});

test.describe("Demo Mode Isolation & Recovery (H)", () => {
  test("preserves Demo Mode isolation when switching cities across Abuja and Nairobi without live requests", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const mockApi = await installMockApi(page);
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();

    // Activate Demo Mode explicitly
    mockApi.clearRequests();
    const banner = page.getByRole("region", {
      name: /Environmental data provenance disclosure notice/i,
    });
    await banner.getByRole("button", { name: /Use Demo Data Mode/i }).click();

    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();
    await expect(page.getByText(/DEMO \/ SAMPLE/i)).toBeVisible();
    await expect(
      page.getByText(/EXPLICIT DEMO MODE ACTIVE — Predictive Intelligence Paused/i)
    ).toBeVisible();
    await expect(
      page.locator("#section-pollutants").getByText("Demo Sample").first()
    ).toBeVisible();

    // Switch to Abuja via quick city switcher while in Demo Mode
    const quickSwitcher = page.getByRole("group", {
      name: /Quick urban location switcher/i,
    });
    await quickSwitcher.getByRole("button", { name: "Abuja, Nigeria" }).click();

    await expect(
      page.getByRole("heading", { name: /Abuja, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Predictive Risk Intelligence & Activity Planner — Abuja, Nigeria/i,
      })
    ).toBeVisible();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();
    await expect(page.getByText(/DEMO \/ SAMPLE/i)).toBeVisible();
    await expect(
      page.getByText(/EXPLICIT DEMO MODE ACTIVE — Predictive Intelligence Paused/i)
    ).toBeVisible();

    // Clicking the already-selected city button in Demo Mode must also remain isolated
    await quickSwitcher.getByRole("button", { name: "Abuja, Nigeria" }).click();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();

    // Switch to a second city (Nairobi) via dropdown while in Demo Mode
    await page.getByLabel(/Monitored Urban Location/i).selectOption("nairobi-ke");
    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(
      page.getByRole("heading", {
        name: /Historical Air Quality Trends & Insights — Nairobi, Kenya/i,
      })
    ).toBeVisible();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();
    await expect(page.getByText(/DEMO \/ SAMPLE/i)).toBeVisible();

    // Verify ZERO unintended live API requests occurred during Demo Mode activation & city switches
    const unintendedLiveCalls = mockApi.requests.filter(
      (r) =>
        r.pathname.endsWith("/api/v1/air-quality") ||
        r.pathname.endsWith("/api/v1/air-quality/intelligence") ||
        r.pathname.endsWith("/api/v1/air-quality/history") ||
        r.pathname.endsWith("/api/v1/dashboard")
    );
    expect(unintendedLiveCalls).toEqual([]);
    expect(pageErrors).toEqual([]);
  });

  test("restores Live Model Data for the newly selected city after explicit user action", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const mockApi = await installMockApi(page);
    await page.goto("/");
    await expect(
      page.getByRole("heading", { name: /Lagos, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();

    const banner = page.getByRole("region", {
      name: /Environmental data provenance disclosure notice/i,
    });
    await banner.getByRole("button", { name: /Use Demo Data Mode/i }).click();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();

    // Change city to Abuja while in Demo Mode
    const quickSwitcher = page.getByRole("group", {
      name: /Quick urban location switcher/i,
    });
    await quickSwitcher.getByRole("button", { name: "Abuja, Nigeria" }).click();
    await expect(
      page.getByRole("heading", { name: /Abuja, Nigeria Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(banner.getByText("DEMO DATA", { exact: true })).toBeVisible();

    // Explicitly switch back to Live Model Data
    mockApi.clearRequests();
    await banner
      .getByRole("button", { name: /Switch to Live Model Data/i })
      .click();

    await expect(
      banner.getByText(/LIVE PROVIDER DATA — MODEL-BASED ESTIMATE/i)
    ).toBeVisible();
    await expect(page.getByText(/LIVE MODEL/i).first()).toBeVisible();
    await expect(page.locator("#section-summary").getByText("62").first()).toBeVisible();
    await expect(
      page.locator("#section-intelligence").getByText(/Peak Forecast Risk/i).first()
    ).toBeVisible();

    // Verify live API requests were initiated for Abuja
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/intelligence") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/history") &&
          r.searchParams.location_id === "abuja-ng"
      )
    ).toBe(true);
    expect(pageErrors).toEqual([]);
  });
});
