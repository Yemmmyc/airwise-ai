import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { installMockApi } from "./fixtures/mockApi";

interface ViewportSpec {
  name: string;
  category: "mobile" | "tablet" | "desktop";
  width: number;
  height: number;
}

const VIEWPORTS: ViewportSpec[] = [
  { name: "mobile-375x812", category: "mobile", width: 375, height: 812 },
  { name: "mobile-390x844", category: "mobile", width: 390, height: 844 },
  { name: "tablet-768x1024", category: "tablet", width: 768, height: 1024 },
  { name: "tablet-1024x768", category: "tablet", width: 1024, height: 768 },
  { name: "desktop-1280x800", category: "desktop", width: 1280, height: 800 },
  { name: "desktop-1440x900", category: "desktop", width: 1440, height: 900 },
];

const SECTION_IDS = [
  "section-summary",
  "section-map",
  "section-pollutants",
  "section-forecast",
  "section-intelligence",
  "section-history",
  "section-provenance",
  "section-advisory",
  "section-recommendations",
  "section-assistant",
];

const SCREENSHOT_ROOT = path.join(
  process.cwd(),
  "test-results",
  "responsive-qa"
);

test.describe("Responsive & Visual Browser QA (Phase 8 Step 3)", () => {
  for (const vp of VIEWPORTS) {
    test(`validates layout, overflow, usability, and captures screenshots at ${vp.name}`, async ({
      page,
    }) => {
      const pageErrors: string[] = [];
      page.on("pageerror", (error) => pageErrors.push(error.message));

      await page.setViewportSize({ width: vp.width, height: vp.height });
      await installMockApi(page);
      await page.goto("/");

      // Wait for all core async sections to render deterministically
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

      // 1. Measure document horizontal overflow, sidebar/main geometry, sections & internal scrollers
      const metrics = await page.evaluate((sectionIds) => {
        const docEl = document.documentElement;
        const aside = document.querySelector("aside");
        const main = document.querySelector("main");
        const asideRect = aside?.getBoundingClientRect() ?? null;
        const mainRect = main?.getBoundingClientRect() ?? null;

        const sectionMeasurements = sectionIds.map((id) => {
          const el = document.getElementById(id);
          if (!el) {
            return {
              id,
              found: false,
              width: 0,
              height: 0,
              left: 0,
              right: 0,
              scrollWidth: 0,
              clientWidth: 0,
            };
          }
          const r = el.getBoundingClientRect();
          return {
            id,
            found: true,
            width: Math.round(r.width),
            height: Math.round(r.height),
            left: Math.round(r.left),
            right: Math.round(r.right),
            scrollWidth: el.scrollWidth,
            clientWidth: el.clientWidth,
          };
        });

        // Detect intentional internal horizontal scroll containers (overflow-x: auto/scroll)
        const internalScrollers: Array<{
          tag: string;
          className: string;
          scrollWidth: number;
          clientWidth: number;
        }> = [];
        document.querySelectorAll("*").forEach((node) => {
          const el = node as HTMLElement;
          if (el.scrollWidth > el.clientWidth + 2) {
            const style = window.getComputedStyle(el);
            if (style.overflowX === "auto" || style.overflowX === "scroll") {
              internalScrollers.push({
                tag: el.tagName.toLowerCase(),
                className: (el.className || "").toString().slice(0, 80),
                scrollWidth: el.scrollWidth,
                clientWidth: el.clientWidth,
              });
            }
          }
        });

        // Map container dimensions
        const mapApp = document.querySelector('#section-map [role="application"]');
        const mapRect = mapApp?.getBoundingClientRect() ?? null;

        // Key interactive control bounds
        const dropdown = document.querySelector("select");
        const assistantInput = document.getElementById("airwise-assistant-input");
        const dropdownRect = dropdown?.getBoundingClientRect() ?? null;
        const inputRect = assistantInput?.getBoundingClientRect() ?? null;

        // Touch-target height check on first sidebar link and quick city button
        const firstNavLink = document.querySelector("aside nav a");
        const firstQuickBtn = document.querySelector(
          '[role="group"][aria-label="Quick urban location switcher"] button'
        );

        // Find specific elements overflowing the document viewport width
        const overflowCulprits: Array<{
          tag: string;
          sectionId: string;
          right: number;
          width: number;
          text: string;
          className: string;
        }> = [];
        document.querySelectorAll("*").forEach((node) => {
          const el = node as HTMLElement;
          const r = el.getBoundingClientRect();
          if (r.width > 0 && r.height > 0 && r.right > docEl.clientWidth + 2) {
            // Skip elements inside an intentional horizontal scroll container
            let parent = el.parentElement;
            let insideScroller = false;
            while (parent && parent !== document.body) {
              const st = window.getComputedStyle(parent);
              if (
                st.overflowX === "auto" ||
                st.overflowX === "scroll" ||
                st.overflowX === "hidden"
              ) {
                insideScroller = true;
                break;
              }
              parent = parent.parentElement;
            }
            if (!insideScroller) {
              const sec = el.closest("section");
              overflowCulprits.push({
                tag: el.tagName.toLowerCase(),
                sectionId: sec?.id ?? "outside-section",
                right: Math.round(r.right),
                width: Math.round(r.width),
                text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60),
                className: (el.className || "").toString().slice(0, 80),
              });
            }
          }
        });

        // Provenance disclosure banner geometry
        const bannerEl = document.querySelector(
          '[role="region"][aria-label="Environmental data provenance disclosure notice"]'
        );
        const bannerRect = bannerEl?.getBoundingClientRect() ?? null;
        const badgeEl = bannerEl?.querySelector("span") ?? null;
        const badgeRect = badgeEl?.getBoundingClientRect() ?? null;
        const disclaimerEl = bannerEl?.querySelector("p") ?? null;
        const disclaimerRect = disclaimerEl?.getBoundingClientRect() ?? null;
        const bannerButtons = Array.from(
          bannerEl?.querySelectorAll("button") ?? []
        ).map((b) => {
          const r = b.getBoundingClientRect();
          return {
            text: (b.textContent || "").trim(),
            width: Math.round(r.width),
            height: Math.round(r.height),
            right: Math.round(r.right),
          };
        });

        return {
          docScrollWidth: docEl.scrollWidth,
          docClientWidth: docEl.clientWidth,
          docOverflowPx: docEl.scrollWidth - docEl.clientWidth,
          asideHeight: asideRect ? Math.round(asideRect.height) : 0,
          asideWidth: asideRect ? Math.round(asideRect.width) : 0,
          mainLeft: mainRect ? Math.round(mainRect.left) : 0,
          mainWidth: mainRect ? Math.round(mainRect.width) : 0,
          sidebarStacked:
            asideRect && mainRect ? mainRect.top >= asideRect.bottom - 2 : false,
          mapWidth: mapRect ? Math.round(mapRect.width) : 0,
          mapHeight: mapRect ? Math.round(mapRect.height) : 0,
          dropdownRight: dropdownRect ? Math.round(dropdownRect.right) : 0,
          assistantInputRight: inputRect ? Math.round(inputRect.right) : 0,
          navLinkHeight: firstNavLink
            ? Math.round(firstNavLink.getBoundingClientRect().height)
            : 0,
          quickBtnHeight: firstQuickBtn
            ? Math.round(firstQuickBtn.getBoundingClientRect().height)
            : 0,
          banner: {
            width: bannerRect ? Math.round(bannerRect.width) : 0,
            right: bannerRect ? Math.round(bannerRect.right) : 0,
            badgeWidth: badgeRect ? Math.round(badgeRect.width) : 0,
            badgeRight: badgeRect ? Math.round(badgeRect.right) : 0,
            disclaimerWidth: disclaimerRect
              ? Math.round(disclaimerRect.width)
              : 0,
            disclaimerRight: disclaimerRect
              ? Math.round(disclaimerRect.right)
              : 0,
            buttons: bannerButtons,
          },
          sectionMeasurements,
          internalScrollersCount: internalScrollers.length,
          internalScrollers: internalScrollers.slice(0, 6),
          overflowCulprits: overflowCulprits.slice(0, 8),
        };
      }, SECTION_IDS);

      console.log(
        `[responsive:${vp.name}] doc=${metrics.docScrollWidth}/${metrics.docClientWidth} (overflow=${metrics.docOverflowPx}px) bannerBadgeR=${metrics.banner.badgeRight} disclaimerW=${metrics.banner.disclaimerWidth}px disclaimerR=${metrics.banner.disclaimerRight} stacked=${metrics.sidebarStacked} map=${metrics.mapWidth}x${metrics.mapHeight} internalScrollers=${metrics.internalScrollersCount}`
      );
      if (metrics.overflowCulprits.length > 0) {
        console.log(
          `[responsive:${vp.name}:overflowCulprits] ${JSON.stringify(metrics.overflowCulprits)}`
        );
      }

      // 2. Capture deterministic QA screenshots BEFORE strict overflow assertion
      //    so visual artifacts exist for every viewport (stored in gitignored test-results/)
      const vpDir = path.join(SCREENSHOT_ROOT, vp.name);
      fs.mkdirSync(vpDir, { recursive: true });

      const bannerLoc = page.getByRole("region", {
        name: /Environmental data provenance disclosure notice/i,
      });
      await bannerLoc.scrollIntoViewIfNeeded();
      await bannerLoc.screenshot({
        path: path.join(vpDir, "00-provenance-banner.png"),
      });

      await page.evaluate(() => window.scrollTo(0, 0));
      await page.screenshot({
        path: path.join(vpDir, "01-initial-dashboard.png"),
        fullPage: false,
      });

      const sectionShots: Array<[string, string]> = [
        ["#section-summary", "02-aqi-summary.png"],
        ["#section-map", "03-intelligence-map.png"],
        ["#section-intelligence", "04-predictive-intelligence.png"],
        ["#section-history", "05-historical-trends.png"],
        ["#section-assistant", "06-assistant.png"],
      ];

      for (const [selector, filename] of sectionShots) {
        const loc = page.locator(selector);
        await loc.scrollIntoViewIfNeeded();
        await loc.screenshot({ path: path.join(vpDir, filename) });
      }

      // 3. Keyboard focus visibility & skip-to-content usability check
      const skipLink = page.getByRole("link", {
        name: /Skip to main dashboard content/i,
      });
      await skipLink.focus();
      await expect(skipLink).toBeFocused();
      const skipBox = await skipLink.boundingBox();
      expect(skipBox).not.toBeNull();
      expect(skipBox!.width).toBeGreaterThan(40);
      expect(skipBox!.height).toBeGreaterThan(20);

      const firstSidebarLink = page
        .getByRole("navigation", { name: /Dashboard sections/i })
        .getByRole("link")
        .first();
      await firstSidebarLink.focus();
      await expect(firstSidebarLink).toBeFocused();

      // 4. Assert responsive layout & no unintended document-level horizontal overflow
      if (vp.width < 1024) {
        expect(metrics.sidebarStacked).toBe(true);
      } else {
        expect(metrics.sidebarStacked).toBe(false);
        expect(metrics.mainLeft).toBeGreaterThanOrEqual(metrics.asideWidth - 2);
      }

      for (const sec of metrics.sectionMeasurements) {
        expect(sec.found, `Section #${sec.id} missing at ${vp.name}`).toBe(true);
        expect(sec.width, `Section #${sec.id} collapsed at ${vp.name}`).toBeGreaterThan(
          200
        );
      }

      // Provenance disclosure banner containment & readability assertions
      expect(
        metrics.banner.badgeRight,
        `Provenance badge overflows viewport at ${vp.name}`
      ).toBeLessThanOrEqual(vp.width + 1);
      expect(
        metrics.banner.disclaimerRight,
        `Provenance disclaimer overflows banner container at ${vp.name}`
      ).toBeLessThanOrEqual(metrics.banner.right + 1);
      expect(
        metrics.banner.disclaimerWidth,
        `Provenance disclaimer text compressed too narrowly (${metrics.banner.disclaimerWidth}px) at ${vp.name}`
      ).toBeGreaterThanOrEqual(220);
      expect(metrics.banner.buttons.length).toBeGreaterThanOrEqual(2);
      for (const btn of metrics.banner.buttons) {
        expect(btn.width).toBeGreaterThan(60);
        expect(btn.height).toBeGreaterThanOrEqual(24);
        expect(
          btn.right,
          `Provenance action button "${btn.text}" overflows viewport at ${vp.name}`
        ).toBeLessThanOrEqual(vp.width + 1);
      }

      expect(metrics.mapWidth).toBeGreaterThan(200);
      expect(metrics.mapHeight).toBeGreaterThanOrEqual(240);
      expect(metrics.dropdownRight).toBeLessThanOrEqual(vp.width + 1);
      expect(metrics.assistantInputRight).toBeLessThanOrEqual(vp.width + 1);
      expect(pageErrors).toEqual([]);

      expect(
        metrics.docScrollWidth,
        `Document scrollWidth (${metrics.docScrollWidth}) exceeded clientWidth (${metrics.docClientWidth}) at ${vp.name}`
      ).toBeLessThanOrEqual(metrics.docClientWidth + 1);
    });
  }
});
