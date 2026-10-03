import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import AxeBuilder from "@axe-core/playwright";

const here = path.dirname(fileURLToPath(import.meta.url));
process.env.PLAYWRIGHT_BROWSERS_PATH ??= path.join(here, ".playwright");
const { chromium } = await import("playwright");
const chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const browser = await chromium.launch({
  headless: true,
  ...(existsSync(chrome) ? { executablePath: chrome } : {}),
});
const summary = JSON.parse(
  readFileSync(path.join(here, "data/summary.json"), "utf8"),
);
const baseURL = process.env.DOOMLAB_DEMO_URL ?? "http://127.0.0.1:4173";
const failures = [];
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  permissions: ["clipboard-read", "clipboard-write"],
});
const page = await context.newPage();
page.on("pageerror", (error) => failures.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400)
    failures.push(`${response.status()} ${response.url()}`);
});

try {
  await page.goto(baseURL, { waitUntil: "networkidle" });
  await page.evaluate(() => document.fonts.ready);
  assert.equal(
    await page.evaluate(() => document.fonts.check('500 16px "Space Grotesk"')),
    true,
  );
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="held-out"]')].every(
      (video) =>
        video.readyState >= 2 && !video.paused && video.currentTime > 0,
    ),
  );
  assert.equal(await page.locator("#toggle-play").count(), 0);
  assert.equal(await page.locator("#restart-replays").count(), 0);
  console.log("PASS replays autoplay without playback buttons");

  const agents = ["random", "scripted", "react_single", "commander"];
  const scenarios = ["defend_the_center", "health_gathering_supreme"];
  for (const [rowIndex, scenario] of scenarios.entries()) {
    const row = page.locator(".score-table tbody tr").nth(rowIndex);
    for (const [index, agent] of agents.entries()) {
      const source = summary.test.groups[scenario][agent];
      const cell = row.locator("td").nth(index);
      const value = Number(
        (await cell.locator(".score-number").innerText()).replaceAll(",", ""),
      );
      assert.equal(value, source.score.median, `${scenario}/${agent} median`);
      assert.ok(
        (await cell.locator(".success-cell").innerText()).includes(
          `${source.successes}/${source.n}`,
        ),
      );
      assert.match(await cell.locator(".success-cell").innerText(), /\d+–\d+%/);
    }
  }
  for (const [index, source] of summary.trial.ab.entries()) {
    const row = page.locator(".trial-table tbody tr").nth(index);
    assert.equal(Number(await row.locator("th").textContent()), source.seed);
    assert.deepEqual(
      (await row.locator("td").allTextContents()).map((value) =>
        Number(value.replaceAll(",", "")),
      ),
      [source.v0, source.v1],
    );
  }
  assert.deepEqual(
    await page.locator(".lessons q").allTextContents(),
    summary.trial.lessons,
  );
  assert.equal(
    await page.locator(".reviewer-note blockquote").textContent(),
    `“${summary.trial.human_note}”`,
  );
  const flowchart = page.locator(".harness-diagram img");
  await flowchart.scrollIntoViewIfNeeded();
  await page.waitForFunction(() => {
    const image = document.querySelector(".harness-diagram img");
    return image.complete && image.naturalWidth > 0;
  });
  assert.ok(
    await flowchart.evaluate(
      (image) => image.naturalHeight > image.naturalWidth,
    ),
  );
  assert.equal(await page.locator(".timeline-kill").count(), 24);
  assert.equal(await page.locator(".timeline-svg rect").count(), 24);
  assert.equal(await page.locator(".seed-dot").count(), 80);
  assert.equal(await page.locator("#chart-basic").count(), 0);
  assert.equal(await page.locator(".score-table tbody tr").count(), 2);
  console.log(
    "PASS evidence: medians, success counts, intervals, seed pairs, verbatim quotes, and timeline",
  );

  const heldOut = page.locator('video[data-replay-group="held-out"]');
  await heldOut.first().click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="held-out"]')].every(
      (video) => video.paused,
    ),
  );
  await heldOut.last().click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="held-out"]')].every(
      (video) => !video.paused,
    ),
  );
  const trial = page.locator('video[data-replay-group="trial"]');
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="trial"]')].every(
      (video) => !video.paused && video.currentTime > 0,
    ),
  );
  await trial.first().click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="trial"]')].every(
      (video) => video.paused,
    ),
  );
  await trial.last().click();
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="trial"]')].every(
      (video) => !video.paused,
    ),
  );
  assert.equal(
    await trial.evaluateAll((videos) => videos.every((video) => video.loop)),
    true,
  );
  await trial.evaluateAll((videos) =>
    videos.forEach((video) => {
      video.currentTime = video.duration - 0.08;
    }),
  );
  await page.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="trial"]')].every(
      (video) => !video.paused && video.currentTime < 1,
    ),
  );
  console.log("PASS autoplay, native infinite loops, and click-to-pause");

  const theme = page.locator("#theme-toggle");
  const originalTheme = await page.locator("html").getAttribute("data-theme");
  await theme.click();
  await page.waitForFunction(
    () =>
      document.documentElement.dataset.theme !== null &&
      document.querySelector("#theme-toggle").disabled,
  );
  await theme.evaluate((button) =>
    button.dispatchEvent(new MouseEvent("click", { bubbles: true })),
  );
  await page.waitForFunction(
    () => !document.querySelector("#theme-toggle").disabled,
  );
  assert.notEqual(
    await page.locator("html").getAttribute("data-theme"),
    originalTheme,
  );
  assert.equal(
    await page.evaluate(() => localStorage.getItem("doomlab-theme")),
    await page.locator("html").getAttribute("data-theme"),
  );
  await theme.click();
  await page.waitForFunction(
    () => !document.querySelector("#theme-toggle").disabled,
  );
  assert.equal(
    await page.locator("html").getAttribute("data-theme"),
    originalTheme,
  );
  console.log(
    "PASS theme toggle locks repeated clicks until transition finishes",
  );

  await page.locator("#chart-defend .seed-dot").first().focus();
  assert.match(
    await page.locator("#chart-detail").textContent(),
    /Seed 1000 · Random · 334 tics survived · higher is better/,
  );
  const hoverDot = page.locator("#chart-defend .seed-dot").first();
  await hoverDot.hover();
  assert.match(
    await page.locator("#chart-defend .plot-tooltip").innerText(),
    /Seed 1000 · Random · 334/,
  );
  assert.equal(
    await page.locator("#chart-defend .plot-tooltip").isVisible(),
    true,
  );
  assert.equal(await page.locator("#chart-defend .seed-active").count(), 4);
  assert.equal(await page.locator("#chart-supreme").isVisible(), true);
  assert.equal(await page.locator("#theme-toggle").isVisible(), true);
  assert.equal(await page.locator("#theme-toggle").innerText(), "Theme");
  console.log("PASS per-seed hover tooltips and visible theme control");

  await page
    .getByRole("button", { name: "Copy reproduction commands", exact: true })
    .click();
  assert.equal(
    await page.evaluate(() => navigator.clipboard.readText()),
    "uv run doomlab eval --split test\nuv run doomlab report",
  );
  const downloaded = await context.request.get(`${baseURL}/data/summary.json`);
  assert.equal(downloaded.status(), 200);
  assert.deepEqual(await downloaded.json(), summary);
  const trace = await context.request.get(
    `${baseURL}/data/commander-trace.jsonl`,
  );
  assert.equal(trace.status(), 200);
  assert.match(await trace.text(), /"event": "episode_end"/);
  console.log("PASS reproduction commands and downloadable evidence");

  for (const width of [1440, 1024, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => scrollTo({ top: 0, behavior: "instant" }));
    const dimensions = await page.evaluate(() => ({
      viewport: innerWidth,
      content: document.documentElement.scrollWidth,
    }));
    assert.ok(
      dimensions.content <= dimensions.viewport,
      `Page overflows at ${width}px: ${JSON.stringify(dimensions)}`,
    );
    assert.equal(await page.locator("#theme-toggle").isVisible(), true);
    const accessibility = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
      .analyze();
    failures.push(
      ...accessibility.violations.map((violation) => ({
        width,
        id: violation.id,
        nodes: violation.nodes.map((node) => ({
          target: node.target,
          summary: node.failureSummary,
        })),
      })),
    );
    console.log(`Checked ${width}px layout and accessibility`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page
    .getByRole("navigation", { name: "Report contents" })
    .getByRole("link", { name: "Results", exact: true })
    .click();
  assert.equal(new URL(page.url()).hash, "#results");
  console.log("PASS mobile report navigation");

  const reducedPage = await context.newPage();
  await reducedPage.emulateMedia({ reducedMotion: "reduce" });
  await reducedPage.goto(baseURL, { waitUntil: "networkidle" });
  await reducedPage.waitForFunction(() =>
    [...document.querySelectorAll('video[data-replay-group="held-out"]')].every(
      (video) => video.loop && !video.paused && video.currentTime > 0,
    ),
  );
  console.log("PASS videos autoplay and loop with reduced motion enabled");

  const noJS = await browser.newContext({ javaScriptEnabled: false });
  const staticPage = await noJS.newPage();
  await staticPage.goto(baseURL, { waitUntil: "networkidle" });
  assert.equal(await staticPage.locator(".score-table tbody tr").count(), 2);
  assert.equal(await staticPage.locator(".lessons q").count(), 3);
  assert.equal(
    await staticPage.locator(".reviewer-note blockquote").isVisible(),
    true,
  );
  assert.equal(await staticPage.locator("#chart-supreme").isVisible(), true);
  assert.equal(await staticPage.locator("#lessons-learned").isVisible(), true);
  await noJS.close();
  console.log("PASS complete report is readable without JavaScript");

  assert.deepEqual(
    failures,
    [],
    `Browser or accessibility failures:\n${JSON.stringify(failures, null, 2)}`,
  );
  console.log("All browser checks passed. No screenshots were saved.");
} finally {
  await browser.close();
}
