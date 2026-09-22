// Browser behaviour tests for the HA Docs site scripts (Plan 021).
//
// Serves a site built from mkdocs.test.yml under a fake ingress prefix - the
// scripts must derive every URL from their own src, never from location - and
// drives it in Chromium and WebKit. /anno/* is answered by page.route(), so no
// add-on process is needed.
//
//   HA_DOCS_TEST_SITE=<built site dir> node --test tests/browser/run.mjs
//   HA_DOCS_BROWSERS=chromium            (optional; default both)

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { chromium, webkit } from "playwright";

const SITE = process.env.HA_DOCS_TEST_SITE;
if (!SITE) {
  throw new Error("HA_DOCS_TEST_SITE must point at a built fixture site");
}
const PREFIX = "/api/hassio_ingress/tok-test-123/";
const ENGINES = { chromium, webkit };
const WANTED = (process.env.HA_DOCS_BROWSERS || "chromium,webkit").split(",");

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".xml": "application/xml"
};

let server;
let origin;

before(async () => {
  server = http.createServer((req, res) => {
    const url = new URL(req.url, "http://x");
    if (!url.pathname.startsWith(PREFIX)) {
      res.writeHead(404).end();
      return;
    }
    const rel = decodeURIComponent(url.pathname.slice(PREFIX.length)) || "index.html";
    const file = path.join(SITE, rel);
    if (!file.startsWith(path.resolve(SITE)) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      res.writeHead(404).end();
      return;
    }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
});

after(() => server.close());

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Fixed for the whole run, as it is for a real idle add-on: a timestamp that
// moved on every poll would (rightly) make every poll repaint.
const FINISHED = Date.now() / 1000 - 10;

function scanPayload() {
  const finished = FINISHED;
  return {
    enabled: true,
    watcher: true,
    source: { checked: 10, broken: 0, finished },
    repairs: { state: "idle", issues: [], finished, healthy: 5, raised: 0 },
    recent: []
  };
}

// Opens a page with /anno/ mocked and every request recorded.
async function open(browser, page_, { width = 1280, height = 700, scanDelay = 0 } = {}) {
  const context = await browser.newContext({ viewport: { width, height } });
  const page = await context.newPage();
  const stats = { scan: 0, inflight: 0, maxInflight: 0, requests: [], errors: [] };
  page.on("request", (request) => stats.requests.push(request.url()));
  page.on("pageerror", (error) => stats.errors.push(String(error)));
  await page.route("**/anno/**", async (route) => {
    const name = new URL(route.request().url()).pathname.split("/anno/")[1];
    if (name === "scan") {
      stats.scan += 1;
      stats.inflight += 1;
      stats.maxInflight = Math.max(stats.maxInflight, stats.inflight);
      await sleep(scanDelay);
      stats.inflight -= 1;
      await route.fulfill({ json: scanPayload() });
    } else if (name === "all") {
      await route.fulfill({ json: { annotations: [] } });
    } else {
      await route.fulfill({ json: {} });
    }
  });
  await page.goto(origin + PREFIX + page_, { waitUntil: "domcontentloaded" });
  return { context, page, stats };
}

const runtimeRequests = (stats) => stats.requests.filter((u) => u.endsWith("/assets/mermaid.min.js"));
const offsite = (stats) => stats.requests.filter((u) => !u.startsWith(origin));

// Runs in the page: true once every listed .diagram has finished.
function allDrawn(indexes) {
  const els = document.querySelectorAll(".diagram");
  return indexes.every((i) => els[i] && els[i].getAttribute("data-diagram-state") === "drawn");
}

for (const name of WANTED) {
  let browser;

  test(`${name}`, async (t) => {
    // HA_DOCS_CHROMIUM_CHANNEL=msedge|chrome runs Chromium from an installed
    // browser, for a workstation that cannot download Playwright's own.
    const channel = name === "chromium" ? process.env.HA_DOCS_CHROMIUM_CHANNEL : undefined;
    browser = await ENGINES[name].launch(channel ? { channel } : {});
    try {
      await t.test("a page with no diagram never requests the runtime", async () => {
        const { context, page, stats } = await open(browser, "index.html");
        await page.waitForLoadState("load");
        await sleep(500);
        assert.equal(runtimeRequests(stats).length, 0);
        assert.deepEqual(offsite(stats), []);
        assert.deepEqual(stats.errors, []);
        await context.close();
      });

      await t.test("diagrams load the runtime once, from under the ingress prefix", async () => {
        const { context, page, stats } = await open(browser, "diagrams.html");
        await page.waitForFunction(allDrawn, [0, 1, 2], { timeout: 20000 });
        const runtime = runtimeRequests(stats);
        assert.equal(runtime.length, 1);
        assert.ok(runtime[0].startsWith(origin + PREFIX), runtime[0]);
        assert.deepEqual(offsite(stats), []);

        const shapes = await page.$$eval(".diagram", (els) =>
          els.map((el) => ({
            svg: !!el.querySelector("svg"),
            error: el.classList.contains("diagram--error"),
            text: el.textContent.slice(0, 40),
            id: (el.querySelector("svg") || {}).id || null
          }))
        );
        assert.ok(shapes[0].svg && shapes[1].svg, "top diagrams did not render");
        assert.notEqual(shapes[0].id, shapes[1].id, "two diagrams share an SVG id");
        assert.ok(shapes[2].error, "the broken diagram is not flagged");
        assert.match(shapes[2].text, /^Diagram failed to render/);
        assert.deepEqual(stats.errors, []);
        await context.close();
      });

      await t.test("a diagram far below the fold waits until it is scrolled to", async () => {
        const { context, page } = await open(browser, "diagrams.html");
        await page.waitForFunction(allDrawn, [0, 1, 2], { timeout: 20000 });
        await sleep(300);
        const before = await page.locator(".diagram").last().getAttribute("data-diagram-state");
        assert.equal(before, "waiting");
        await page.locator(".diagram").last().scrollIntoViewIfNeeded();
        await page.waitForFunction(allDrawn, [3], { timeout: 20000 });
        assert.ok(await page.locator(".diagram").last().locator("svg").count());
        await context.close();
      });

      await t.test("palette changes mid-render end in the final theme", async () => {
        const { context, page, stats } = await open(browser, "diagrams.html");
        // Straight away, while the runtime is still loading or rendering.
        await page.evaluate(() => {
          const body = document.body;
          body.setAttribute("data-md-color-scheme", "slate");
          body.setAttribute("data-md-color-scheme", "default");
          body.setAttribute("data-md-color-scheme", "slate");
        });
        await page.waitForFunction(allDrawn, [0, 1, 2], { timeout: 20000 });
        // And again once everything is drawn.
        await page.evaluate(() => document.body.setAttribute("data-md-color-scheme", "default"));
        await page.evaluate(() => document.body.setAttribute("data-md-color-scheme", "slate"));
        await page.waitForFunction(allDrawn, [0, 1, 2], { timeout: 20000 });
        await sleep(500);
        const flow = await page.$eval(".diagram", (el) => el.innerHTML.toLowerCase());
        // Mermaid's light theme fills flowchart nodes #ECECFF; its dark theme
        // does not use that colour at all.
        assert.ok(!flow.includes("#ececff"), "a light-theme render survived the switch to dark");
        assert.ok(flow.includes("<svg"), "the diagram is not drawn");
        assert.equal(runtimeRequests(stats).length, 1, "the runtime was requested twice");
        assert.equal(
          await page.locator(".diagram").nth(2).evaluate((el) => el.classList.contains("diagram--error")),
          true
        );
        assert.deepEqual(stats.errors, []);
        await context.close();
      });

      await t.test("checker never has two status requests in flight", async () => {
        const { context, page, stats } = await open(browser, "index.html", { scanDelay: 800 });
        await page.waitForSelector(".chk-open");
        // The load poll is now in flight. Pile on every other trigger.
        await page.click(".chk-open");
        await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
        await sleep(1500);
        assert.equal(stats.maxInflight, 1);
        await context.close();
      });

      await t.test("an unchanged status leaves the open panel's rows alone", async () => {
        const { context, page, stats } = await open(browser, "index.html");
        await page.click(".chk-open");
        await page.waitForSelector(".chk-body .chk-section");
        await page.evaluate(() => {
          window.__firstSection = document.querySelector(".chk-body .chk-section");
        });
        const polls = stats.scan;
        await sleep(6800); // two 3 s polls while open
        assert.ok(stats.scan >= polls + 2, `only ${stats.scan - polls} polls`);
        assert.ok(
          await page.evaluate(() => window.__firstSection.isConnected),
          "the panel was rebuilt although nothing changed"
        );
        await context.close();
      });

      await t.test("on a narrow screen the panel lives in the highlights drawer", async () => {
        const { context, page } = await open(browser, "index.html", { width: 400, height: 800 });
        await page.click(".anno-open");
        await page.waitForSelector(".anno-drawer__extra .chk-section");
        await page.evaluate(() => {
          window.__firstSection = document.querySelector(".anno-drawer__extra .chk-section");
        });
        await sleep(3600);
        assert.ok(await page.evaluate(() => window.__firstSection.isConnected));
        await context.close();
      });
    } finally {
      await browser.close();
    }
  });
}
