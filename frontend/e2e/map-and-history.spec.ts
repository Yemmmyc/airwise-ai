import { expect, test } from "@playwright/test";
import { installMockApi } from "./fixtures/mockApi";

test.describe("Intelligence Map (D)", () => {
  test("mounts with 4 canonical cities, synchronizes dashboard on selection, and updates marker details", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await installMockApi(page);
    await page.goto("/");

    const mapSection = page.locator("#section-map");
    await expect(mapSection).toBeVisible();

    // Interactive Leaflet container mounts with stubbed offline tiles
    await expect(
      mapSection.getByRole("application", {
        name: /Interactive Africa Air Quality Intelligence Map/i,
      })
    ).toBeVisible();

    // Configured cities list shows all 4 canonical cities
    const cityList = mapSection.getByRole("list", {
      name: /Configured African cities air quality status/i,
    });
    await expect(cityList).toBeVisible();
    const cityItems = cityList.getByRole("listitem");
    await expect(cityItems).toHaveCount(4);

    for (const cityName of [
      "Lagos, Nigeria",
      "Abuja, Nigeria",
      "Nairobi, Kenya",
      "Accra, Ghana",
    ]) {
      await expect(cityList.getByText(cityName)).toBeVisible();
    }

    // Select Nairobi from the map city list and verify dashboard synchronization
    await cityList.getByText("Nairobi, Kenya").click();

    await expect(
      page.getByRole("heading", { name: /Nairobi, Kenya Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(
      mapSection.getByText(/Nairobi, Kenya \(nairobi-ke\)/i)
    ).toBeVisible();
    await expect(mapSection.getByText(/44 \(Good\)/i)).toBeVisible();

    // Select Accra from the map city list and verify marker details update
    await cityList.getByText("Accra, Ghana").click();
    await expect(
      page.getByRole("heading", { name: /Accra, Ghana Air Quality Dashboard/i })
    ).toBeVisible();
    await expect(
      mapSection.getByText(/Accra, Ghana \(accra-gh\)/i)
    ).toBeVisible();
    await expect(mapSection.getByText(/56 \(Moderate\)/i)).toBeVisible();

    expect(pageErrors).toEqual([]);
  });
});

test.describe("Historical Trends (E)", () => {
  test("supports 7d/14d/30d ranges, metrics, daily/hourly granularity, 4-city comparison, data table, and keyboard chart focus", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const mockApi = await installMockApi(page);
    await page.goto("/");

    const historySection = page.locator("#section-history");
    await expect(historySection).toBeVisible();
    await expect(
      historySection.getByRole("heading", {
        name: /Daily US AQI Trend \(7 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();

    // Range switching: 14 Days and 30 Days
    const rangeGroup = historySection.getByRole("group", {
      name: /Historical date range selector/i,
    });

    mockApi.clearRequests();
    await rangeGroup.getByRole("button", { name: "14 Days" }).click();
    await expect(
      rangeGroup.getByRole("button", { name: "14 Days" })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      historySection.getByRole("heading", {
        name: /Daily US AQI Trend \(14 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/history") &&
          r.searchParams.days === "14"
      )
    ).toBe(true);

    mockApi.clearRequests();
    await rangeGroup.getByRole("button", { name: "30 Days" }).click();
    await expect(
      rangeGroup.getByRole("button", { name: "30 Days" })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      historySection.getByRole("heading", {
        name: /Daily US AQI Trend \(30 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();
    expect(
      mockApi.requests.some(
        (r) =>
          r.pathname.endsWith("/api/v1/air-quality/history") &&
          r.searchParams.days === "30"
      )
    ).toBe(true);

    // Return to 7 Days for hourly granularity check
    await rangeGroup.getByRole("button", { name: "7 Days" }).click();
    await expect(
      historySection.getByRole("heading", {
        name: /Daily US AQI Trend \(7 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();

    // Metric selection: switch to PM2.5 and back to US AQI
    const metricGroup = historySection.getByRole("group", {
      name: /Select historical air quality metric/i,
    });
    await metricGroup.getByRole("button", { name: "PM2.5" }).click();
    await expect(
      metricGroup.getByRole("button", { name: "PM2.5" })
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      historySection.getByRole("heading", {
        name: /Daily PM2\.5 Trend \(7 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();

    await metricGroup.getByRole("button", { name: "US AQI" }).click();
    await expect(
      historySection.getByRole("heading", {
        name: /Daily US AQI Trend \(7 Days — Lagos, Nigeria\)/i,
      })
    ).toBeVisible();

    // Keyboard-focusable chart elements update selected day status
    const firstChartPoint = historySection
      .locator('svg circle[tabindex="0"]')
      .first();
    await expect(firstChartPoint).toBeVisible();
    await firstChartPoint.focus();
    await expect(firstChartPoint).toBeFocused();
    await expect(
      historySection.getByRole("status").getByText("2026-11-14")
    ).toBeVisible();

    // Expandable accessible daily data table
    const tableSummary = historySection.getByText(
      /View Accessible Daily Historical Data Table/i
    );
    await tableSummary.click();
    const dataTable = historySection.locator("table").first();
    await expect(dataTable).toBeVisible();
    await expect(dataTable.getByText("2026-11-14")).toBeVisible();

    // Granularity switch: Daily -> Hourly (7d only) -> Daily
    const granularityGroup = historySection.getByRole("group", {
      name: /Historical chart granularity/i,
    });
    const hourlyBtn = granularityGroup.getByRole("button", {
      name: /Hourly/i,
    });
    await hourlyBtn.click();
    await expect(hourlyBtn).toHaveAttribute("aria-pressed", "true");
    await expect(
      historySection.getByRole("heading", {
        name: /Hourly US AQI/i,
      })
    ).toBeVisible();

    await granularityGroup
      .getByRole("button", { name: /Daily Summary/i })
      .click();

    // Single-city <-> 4-City Comparison tab mode
    mockApi.clearRequests();
    const compareTab = historySection.getByRole("tab", {
      name: /4-City Comparison/i,
    });
    await compareTab.click();
    await expect(compareTab).toHaveAttribute("aria-selected", "true");

    expect(
      mockApi.requests.some((r) =>
        r.pathname.endsWith("/api/v1/air-quality/history/compare")
      )
    ).toBe(true);

    for (const city of ["Lagos", "Abuja", "Nairobi", "Accra"]) {
      await expect(historySection.getByText(city).first()).toBeVisible();
    }

    // Switch back to single-city trends tab
    const singleCityTab = historySection.getByRole("tab", {
      name: /Lagos Trends/i,
    });
    await singleCityTab.click();
    await expect(singleCityTab).toHaveAttribute("aria-selected", "true");

    expect(pageErrors).toEqual([]);
  });
});
