/**
 * Verify every generated page: no broken images, no leftover ScribeHow links,
 * and no dead internal links. Also writes reference screenshots.
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const ROOT = __dirname;
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const BASE = "http://127.0.0.1:8899";
const SHOT_DIR = path.join(ROOT, "preview");

async function check(page, url) {
  await page.goto(url, { waitUntil: "load", timeout: 60000 });
  await page.evaluate(async () => {
    const delay = (ms) => new Promise((r) => setTimeout(r, ms));
    document.querySelectorAll("img").forEach((i) => {
      i.loading = "eager";
      i.removeAttribute("decoding");
    });
    const h = document.body.scrollHeight;
    for (let y = 0; y <= h; y += 800) {
      window.scrollTo(0, y);
      await delay(30);
    }
    window.scrollTo(0, 0);
    await Promise.all(
      Array.from(document.images).map((i) =>
        i.complete ? Promise.resolve() : new Promise((r) => {
          i.addEventListener("load", r, { once: true });
          i.addEventListener("error", r, { once: true });
          setTimeout(r, 15000);
        })
      )
    );
  });

  return page.evaluate(() => {
    const broken = Array.from(document.images)
      .filter((i) => !i.complete || i.naturalWidth === 0)
      .map((i) => i.getAttribute("src"));
    const links = Array.from(document.querySelectorAll("a[href]")).map((a) => a.getAttribute("href"));
    return {
      title: document.title,
      images: document.images.length,
      broken,
      steps: document.querySelectorAll(".step").length,
      notes: document.querySelectorAll(".note").length,
      overlays: document.querySelectorAll(".overlay").length,
      external: links.filter((h) => /scribehow\.com/i.test(h)),
      internal: links.filter((h) => h && !/^(https?:|mailto:|#)/i.test(h)),
    };
  });
}

(async () => {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const guides = JSON.parse(fs.readFileSync(path.join(ROOT, "site-guides.json"), "utf8")).filter(
    (g) => g.url && fs.existsSync(path.join(ROOT, "guide-content", `${g.slug}.json`))
  );

  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--hide-scrollbars"],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1180, height: 1400, deviceScaleFactor: 1 });

  const problems = [];
  let totals = { images: 0, steps: 0, notes: 0, overlays: 0 };

  const index = await check(page, `${BASE}/index.html`);
  console.log(`index.html: ${index.images} images, broken=${index.broken.length}, scribehow links=${index.external.length}`);
  if (index.broken.length) problems.push(`index broken images: ${index.broken.join(", ")}`);
  if (index.external.length) problems.push(`index still links to scribehow: ${index.external.join(", ")}`);
  for (const href of index.internal) {
    // These are authenticated Express routes, not static files.
    if (/^edit\//i.test(href)) continue;
    const target = path.join(ROOT, decodeURIComponent(href.split("#")[0]));
    if (!fs.existsSync(target)) problems.push(`index dead link: ${href}`);
  }

  const shots = new Set(["adjust-kds-routing", "pitco-fryers", "making-schedule-in-rti-xbo", "duke-broiler-cleaning"]);

  for (const g of guides) {
    const res = await check(page, `${BASE}/guides/${g.slug}.html`);
    totals.images += res.images;
    totals.steps += res.steps;
    totals.notes += res.notes;
    totals.overlays += res.overlays;
    const flags = [];
    if (res.broken.length) flags.push(`BROKEN(${res.broken.length}) ${res.broken.slice(0, 2).join(",")}`);
    if (res.external.length) flags.push(`SCRIBEHOW(${res.external.length})`);
    for (const href of res.internal) {
      const target = path.join(ROOT, "guides", decodeURIComponent(href.split("#")[0]));
      if (!fs.existsSync(target)) flags.push(`DEAD ${href}`);
    }
    if (flags.length) problems.push(`${g.slug}: ${flags.join(" | ")}`);
    console.log(
      `${flags.length ? "!!" : "ok"} ${g.slug}: ${res.steps} steps, ${res.images} imgs, ${res.notes} notes, ${res.overlays} overlays ${flags.join(" ")}`
    );
    if (shots.has(g.slug)) {
      await page.screenshot({ path: path.join(SHOT_DIR, `${g.slug}.png`), fullPage: false });
    }
  }

  await browser.close();
  console.log(`\nTOTALS ${JSON.stringify(totals)}`);
  if (problems.length) {
    console.log(`\nPROBLEMS (${problems.length}):`);
    problems.forEach((p) => console.log("  " + p));
    process.exitCode = 1;
  } else {
    console.log("\nNo problems found.");
  }
})();
