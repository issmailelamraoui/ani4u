/** Run against Next + FastAPI. Requires Playwright, independently of production dependencies. */
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";

const { chromium } = createRequire(import.meta.url)(process.env.PLAYWRIGHT_MODULE || "playwright");
const frontend = process.env.FRONTEND_URL || "http://localhost:3000";
const backend = process.env.BACKEND_URL || "http://127.0.0.1:8000";
const output = process.env.ARTIFACT_DIR || "/tmp/nova-catalog-verification";
await mkdir(output, { recursive: true });
async function catalog(path) {
  const response = await fetch(`${backend}/api/catalog/${path}`);
  assert.equal(response.status, 200, `Backend ${path}`);
  return (await response.json()).data;
}
async function navigate(page, path) {
  const response = await page.goto(frontend + path, { waitUntil: "domcontentloaded" });
  assert.equal(response.status(), 200, path);
}
async function noOverflow(page) {
  assert.ok(await page.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) <= innerWidth + 1), "Horizontal overflow");
}

const home = await catalog("home");
const second = await catalog("discover?page=2");
const browser = await chromium.launch({ headless: true });
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: "reduce" });
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  await navigate(page, "/");
  await page.waitForSelector(".nova-hero");
  assert.equal(await page.locator("#discover .nova-card").count(), home.discover.items.length);
  assert.equal(await page.locator(".nova-ranked-row .nova-card").count(), home.topRated.length);
  assert.equal(await page.locator('a[href^="/watch/"]').count(), 0);
  assert.ok((await page.locator("#discover .nova-card").first().getAttribute("href")).startsWith("/anime/catalog/"));
  await noOverflow(page);

  // A failing CDN image is replaced locally, without losing its card/title/link.
  const image = page.locator("#discover .nova-card img").first();
  await image.dispatchEvent("error");
  await page.waitForSelector("#discover .nova-card .nova-art-placeholder");
  assert.equal(await page.locator("#discover .nova-card").count(), home.discover.items.length);

  const initialTitle = await page.locator(".nova-hero h1").innerText();
  await page.getByRole("button", { name: "العنوان التالي", exact: true }).click();
  assert.notEqual(await page.locator(".nova-hero h1").innerText(), initialTitle);
  await page.getByRole("button", { name: "العنوان السابق", exact: true }).click();
  assert.equal(await page.locator(".nova-hero h1").innerText(), initialTitle);
  await page.clock.install();
  await page.locator(".nova-hero-controls button").first().evaluate((element) => element.blur());
  await page.mouse.move(1, 1);
  await page.clock.runFor(9500);
  assert.equal(await page.locator(".nova-hero h1").innerText(), initialTitle, "Reduced motion must disable rotation");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await page.clock.runFor(9500);
  assert.notEqual(await page.locator(".nova-hero h1").innerText(), initialTitle, "Carousel should rotate");
  await page.getByRole("button", { name: "إيقاف العرض التلقائي", exact: true }).click();
  const pausedTitle = await page.locator(".nova-hero h1").innerText();
  await page.locator(".nova-hero-controls button").last().evaluate((element) => element.blur());
  await page.mouse.move(1, 1);
  await page.clock.runFor(19000);
  assert.equal(await page.locator(".nova-hero h1").innerText(), pausedTitle, "Explicit pause must persist");
  await page.emulateMedia({ reducedMotion: "reduce" });

  await page.route("**/api/catalog/discover?*", (route) => route.fulfill({ status: 503, contentType: "application/json", body: '{}' }), { times: 1 });
  await page.getByRole("button", { name: "المزيد من العوالم" }).click();
  await page.waitForSelector('.nova-load-more [role="alert"]');
  assert.equal(await page.locator("#discover .nova-card").count(), home.discover.items.length);
  await page.getByRole("button", { name: "حاول مجددًا", exact: true }).click();
  const expected = new Set([...home.discover.items, ...second.items].map((anime) => anime.id)).size;
  await page.waitForFunction((count) => document.querySelectorAll("#discover .nova-card").length === count, expected);
  await page.screenshot({ path: join(output, "home-desktop.png"), fullPage: true });

  const search = await catalog("search?q=One%20Piece&page=1");
  await navigate(page, "/search?q=One%20Piece");
  assert.equal(await page.locator(".nova-card").count(), search.items.length);
  assert.deepEqual(await page.locator(".nova-card h3").allTextContents(), search.items.map((anime) => anime.title));
  if (search.hasNextPage) {
    await page.getByRole("link", { name: "الصفحة التالية", exact: true }).click();
    await page.waitForURL("**&page=2");
    const searchNext = await catalog("search?q=One%20Piece&page=2");
    await page.waitForFunction((count) => document.querySelectorAll(".nova-card").length === count, searchNext.items.length);
  }
  const anime = home.featured[0];
  await navigate(page, `/anime/catalog/${anime.slug}`);
  assert.equal(await page.locator("h1").innerText(), anime.title);
  assert.equal(await page.locator('iframe, a[href^="/watch/"]').count(), 0);
  await noOverflow(page);
  await page.screenshot({ path: join(output, "catalog-detail.png"), fullPage: true });

  const mobile = await context.newPage();
  mobile.on("pageerror", (error) => errors.push(error.message));
  await mobile.setViewportSize({ width: 390, height: 844 });
  await navigate(mobile, "/");
  await noOverflow(mobile);
  await mobile.screenshot({ path: join(output, "home-mobile.png") });
  await mobile.setViewportSize({ width: 320, height: 740 });
  await noOverflow(mobile);
  await navigate(mobile, `/anime/catalog/${anime.slug}`);
  await noOverflow(mobile);

  const noJs = await browser.newContext({ javaScriptEnabled: false });
  const html = await noJs.newPage();
  await navigate(html, "/");
  assert.equal(await html.locator("#discover .nova-card").count(), home.discover.items.length);
  await navigate(html, "/search?q=One%20Piece");
  assert.equal(await html.locator(".nova-card").count(), search.items.length);
  await noJs.close();
  assert.deepEqual(errors, [], "Browser runtime errors");
  console.log("PASS: catalog SSR, pagination/retry, carousel controls, reduced motion, image fallback, details, and desktop/mobile layout.");
  console.log(`Screenshots: ${output}`);
} finally {
  await browser.close();
}
