import { expect, test } from "@playwright/test";
import {
  buildMockAssistantStatusResponse,
  buildMockPredictiveIntelligenceInsufficientData,
  installMockApi,
} from "./fixtures/mockApi";

test.describe("Predictive Intelligence (F)", () => {
  test("renders Peak Forecast Risk, windows, spikes, activity planner, trends, and expandable data quality", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await installMockApi(page);
    await page.goto("/");

    const section = page.locator("#section-intelligence");
    await expect(section).toBeVisible();

    // Peak Forecast Risk & category distribution
    await expect(
      section.getByText(/Peak Forecast Risk \(24-Hour Horizon/i)
    ).toBeVisible();
    await expect(
      section.getByText("Unhealthy for Sensitive Groups").first()
    ).toBeVisible();
    await expect(section.getByText("120").first()).toBeVisible();
    await expect(section.getByText(/Moderate: 21h \(87\.5%\)/i)).toBeVisible();

    // Elevated-risk window
    await expect(
      section.getByRole("heading", { name: /Elevated-Risk Windows/i })
    ).toBeVisible();
    await expect(section.getByText(/14:00 – 16:00/i)).toBeVisible();
    await expect(section.getByText(/3h window/i)).toBeVisible();

    // Single-hour spikes
    await expect(
      section.getByText(/Isolated Single-Hour Spikes \(1\)/i)
    ).toBeVisible();
    await expect(section.getByText(/AQI 108/i)).toBeVisible();

    // Comparatively favorable (better) windows
    await expect(
      section.getByRole("heading", { name: /Comparatively Favorable Windows/i })
    ).toBeVisible();
    await expect(section.getByText(/06:00 – 09:00/i).first()).toBeVisible();
    await expect(section.getByText(/4h comparative window/i)).toBeVisible();

    // Activity Planner cards (all 3)
    await expect(
      section.getByRole("heading", { name: "Outdoor Exercise" })
    ).toBeVisible();
    await expect(
      section.getByRole("heading", { name: "Outdoor Errands" })
    ).toBeVisible();
    await expect(
      section.getByRole("heading", { name: "General Outdoor Time" })
    ).toBeVisible();

    // Trend indicators
    await expect(
      section.getByRole("heading", { name: /24-Hour Forecast Trend Signals/i })
    ).toBeVisible();
    await expect(section.getByText("Rising").first()).toBeVisible();
    await expect(section.getByText("Stable").first()).toBeVisible();

    // Expandable Data-Quality Evidence <details>
    const qualitySummary = section.getByText(
      /Forecast Data-Quality Evidence \(High • 24\/24 valid hours • continuous\)/i
    );
    await expect(qualitySummary).toBeVisible();
    await qualitySummary.click();
    await expect(
      section.getByText(/Important Data-Quality Disclosure:/i)
    ).toBeVisible();
    await expect(section.getByText(/100% \(0 missing\)/i)).toBeVisible();

    expect(pageErrors).toEqual([]);
  });

  test("handles insufficient-data predictive intelligence conditions transparently", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await installMockApi(page, {
      overrides: {
        intelligence: {
          status: 200,
          body: buildMockPredictiveIntelligenceInsufficientData("lagos-ng"),
        },
      },
    });
    await page.goto("/");

    const section = page.locator("#section-intelligence");
    await expect(section).toBeVisible();
    await expect(
      section.getByText(/Data Quality: Insufficient data \(0%\)/i)
    ).toBeVisible();
    await expect(
      section.getByText(/Insufficient data to evaluate risk windows:/i)
    ).toBeVisible();
    await expect(
      section.getByText(/No comparatively favorable window identified:/i)
    ).toBeVisible();
    await expect(
      section.getByText(/Insufficient Data/i).first()
    ).toBeVisible();

    expect(pageErrors).toEqual([]);
  });
});

test.describe("Assistant Interface (G)", () => {
  test("renders status, switches capability tabs, validates input, selects pollutants, and displays mocked responses & city comparison", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    const mockApi = await installMockApi(page);
    await page.goto("/");

    const section = page.locator("#section-assistant");
    await expect(section).toBeVisible();

    // Status pill renders
    await expect(
      section.getByText(/Gemini Ready \(gemini-2\.5-flash\)/i)
    ).toBeVisible();

    // Capability tabs switch correctly
    const tablist = section.getByRole("tablist", {
      name: /AIRWISE AI Assistant Capability Modes/i,
    });
    const pollutantTab = tablist.getByRole("tab", {
      name: /Pollutant Education/i,
    });
    await pollutantTab.click();
    await expect(pollutantTab).toHaveAttribute("aria-selected", "true");

    // Pollutant selection pills appear in Pollutant Education mode
    const o3Button = section.getByRole("button", { name: "O3", exact: true });
    await expect(o3Button).toBeVisible();
    await o3Button.click();
    await expect(o3Button).toHaveAttribute("aria-pressed", "true");

    // Input validation: disabled for empty or 1-char input, enabled for >= 2 chars
    const input = section.locator("#airwise-assistant-input");
    const submitBtn = section.getByRole("button", { name: "Ask AIRWISE AI" });
    await expect(submitBtn).toBeDisabled();

    await input.fill("A");
    await expect(submitBtn).toBeDisabled();

    await input.fill("Explain O3 in Lagos");
    await expect(submitBtn).toBeEnabled();

    // Submit custom question in Pollutant Education mode
    mockApi.clearRequests();
    await submitBtn.click();

    await expect(section.getByText(/1\. Verified Provider Data/i)).toBeVisible();
    await expect(
      section.getByText(/2\. Forecast Data \(Future Hours Only\)/i)
    ).toBeVisible();
    await expect(
      section.getByText(/3\. AI Interpretation \(Gemini\)/i)
    ).toBeVisible();
    await expect(
      section.getByText(/4\. General Health Guidance \(Non-Medical\)/i)
    ).toBeVisible();
    await expect(section.getByText(/Focus pollutant: O3/i)).toBeVisible();

    // Verify POST payload included pollutant_code: "O3" and mode: "pollutant_education"
    const askReq = mockApi.requests.find((r) =>
      r.pathname.endsWith("/api/v1/assistant/ask")
    );
    expect(askReq?.method).toBe("POST");
    expect(askReq?.postData).toMatchObject({
      location_id: "lagos-ng",
      mode: "pollutant_education",
      pollutant_code: "O3",
    });

    // Suggested prompt in City Comparison mode renders 4-city table
    mockApi.clearRequests();
    await section.getByRole("button", { name: "Compare all 4 cities" }).click();

    await expect(
      section.getByText(/Verified 4-City Model Comparison Snapshot/i)
    ).toBeVisible();
    const comparisonTable = section.locator("table").first();
    for (const city of [
      "Lagos, Nigeria",
      "Abuja, Nigeria",
      "Nairobi, Kenya",
      "Accra, Ghana",
    ]) {
      await expect(comparisonTable.getByText(city)).toBeVisible();
    }

    expect(pageErrors).toEqual([]);
  });

  test("handles assistant unavailable status and 503 responses gracefully", async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));

    await installMockApi(page, {
      overrides: {
        assistantStatus: {
          status: 200,
          body: buildMockAssistantStatusResponse({
            configured: false,
            status: "assistant_unavailable",
            message: "GEMINI_API_KEY is not configured on the backend.",
          }),
        },
        assistantAsk: {
          status: 503,
          body: {
            detail: {
              error_code: "assistant_unavailable",
              message: "Gemini assistant is unavailable without backend credentials.",
            },
          },
        },
      },
    });
    await page.goto("/");

    const section = page.locator("#section-assistant");
    await expect(
      section.getByText(
        /ASSISTANT UNAVAILABLE — Backend Gemini Credentials Required/i
      )
    ).toBeVisible();

    // Submitting a question surfaces the explicit unavailable alert banner
    await section
      .locator("#airwise-assistant-input")
      .fill("How is air quality?");
    await section.getByRole("button", { name: "Ask AIRWISE AI" }).click();

    const alert = section.getByRole("alert");
    await expect(alert).toBeVisible();
    await expect(
      alert.getByText(/AIRWISE AI Assistant Unavailable/i)
    ).toBeVisible();

    // Main live AQI dashboard remains fully operational
    await expect(page.locator("#section-summary").getByText("78").first()).toBeVisible();
    expect(pageErrors).toEqual([]);
  });
});
