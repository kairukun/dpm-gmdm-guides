/**
 * Build clean PDFs by capturing each ScribeHow step as an image,
 * then printing one step per page so screenshots never split.
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");
const puppeteer = require("puppeteer-core");

const ROOT = __dirname;
const OUT_DIR = path.join(ROOT, "pdfs");
const MANIFEST = path.join(ROOT, "guides.json");
const LOG = path.join(ROOT, "pdf-log.txt");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

function log(line) {
  const msg = `[${new Date().toISOString()}] ${line}`;
  console.log(msg);
  fs.appendFileSync(LOG, msg + "\n");
}

function toPrintUrl(url) {
  if (url.includes("/viewer/")) return url.replace("/viewer/", "/shared/");
  return url;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function waitForScreenshots(page) {
  try {
    await page.evaluate(async () => {
      const delay = (ms) => new Promise((r) => setTimeout(r, ms));
      document.querySelectorAll("img").forEach((img) => {
        img.loading = "eager";
        img.decoding = "sync";
      });
      const total = Math.max(document.body.scrollHeight || 0, 1500);
      for (let y = 0; y < total; y += 700) {
        window.scrollTo(0, y);
        await delay(80);
      }
      window.scrollTo(0, 0);
      const imgs = Array.from(
        document.querySelectorAll('[data-testid="action-image-wrapper"] img')
      );
      await Promise.all(
        imgs.map(
          (img) =>
            new Promise((resolve) => {
              if (img.complete && img.naturalWidth > 80) return resolve();
              const done = () => resolve();
              img.addEventListener("load", done, { once: true });
              img.addEventListener("error", done, { once: true });
              setTimeout(done, 15000);
            })
        )
      );
    });
  } catch {}
}

function buildPrintHtml(meta, shots) {
  const [first, ...rest] = shots;
  const restHtml = rest
    .map(
      (b64, i) =>
        `<section class="step"><img alt="Step ${i + 2}" src="data:image/jpeg;base64,${b64}"></section>`
    )
    .join("\n");
  return `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @page { size: Letter; margin: 0.4in; }
  html, body {
    margin: 0;
    padding: 0;
    background: #fff;
    font-family: "Segoe UI", Arial, sans-serif;
    color: #0f172a;
  }
  h1 { font-size: 22px; line-height: 1.25; margin: 0 0 8px; }
  .desc { font-size: 12px; line-height: 1.4; color: #334155; margin: 0 0 12px; }
  .step {
    page-break-after: always;
    break-inside: avoid;
    page-break-inside: avoid;
  }
  .step:last-child { page-break-after: auto; }
  .step img {
    display: block;
    width: 100%;
    height: auto;
    max-height: 9.5in;
    object-fit: contain;
    object-position: top center;
  }
  .first img { max-height: 8.3in; }
</style>
</head>
<body>
  <section class="step first">
    <h1>${escapeHtml(meta.title)}</h1>
    <div class="desc">${escapeHtml(meta.description)}</div>
    <img alt="Step 1" src="data:image/jpeg;base64,${first}">
  </section>
  ${restHtml}
</body>
</html>`;
}

async function captureAllSteps(page) {
  const shots = [];
  const seen = new Set();
  let idleRounds = 0;
  let y = 0;

  for (let round = 0; round < 100 && idleRounds < 4; round++) {
    const infos = await page.$$eval('[data-testid="action-instruction"]', (els) =>
      els.map((el) => {
        const num = el.querySelector("span")?.innerText?.trim() || "";
        const text = (el.innerText || "").replace(/\s+/g, " ").slice(0, 120);
        return `${num}|${text}`;
      })
    );
    const handles = await page.$$('[data-testid="action-instruction"]');
    let added = 0;
    for (let i = 0; i < handles.length; i++) {
      const key = infos[i] || `i${i}`;
      if (seen.has(key)) continue;
      seen.add(key);
      try {
        await handles[i].evaluate((el) => el.scrollIntoView({ block: "center" }));
        await new Promise((r) => setTimeout(r, 60));
        const buf = await handles[i].screenshot({ type: "jpeg", quality: 85 });
        shots.push(Buffer.from(buf).toString("base64"));
        added += 1;
      } catch (err) {
        log(`WARN step capture failed (${key}): ${err.message}`);
      }
    }
    idleRounds = added === 0 ? idleRounds + 1 : 0;
    y += 1000;
    const maxY = await page.evaluate(() => document.body.scrollHeight);
    await page.evaluate((yy) => window.scrollTo(0, yy), y);
    await new Promise((r) => setTimeout(r, 120));
    if (y > maxY + 800 && added === 0) break;
  }
  return shots;
}

function stripEmptyPages(pdfPath) {
  const result = spawnSync(
    "python",
    [path.join(ROOT, "clean_pdfs.py"), "--strip", path.basename(pdfPath)],
    { encoding: "utf8" }
  );
  if (result.stdout) {
    const lines = result.stdout.trim().split("\n");
    log(`STRIP ${lines[lines.length - 1]}`);
  }
}

async function newPage(browser) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 2200, deviceScaleFactor: 1.2 });
  await page.setUserAgent(
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
  );
  page.setDefaultNavigationTimeout(90000);
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
  return page;
}

async function printOne(page, guide, { force }) {
  const dest = path.join(OUT_DIR, guide.filename);
  if (!force && fs.existsSync(dest) && fs.statSync(dest).size > 20000) {
    log(`SKIP exists ${guide.filename}`);
    return "skipped";
  }
  const url = toPrintUrl(guide.url);
  log(`OPEN ${url}`);
  const resp = await page.goto(url, { waitUntil: "load", timeout: 90000 });
  const status = resp ? resp.status() : 0;
  if (status >= 400) throw new Error(`HTTP ${status} for ${url}`);
  try {
    await page.waitForSelector('[data-testid="action-instruction"]', { timeout: 25000 });
  } catch {
    try {
      await page.waitForSelector("h1", { timeout: 8000 });
    } catch {}
  }
  await waitForScreenshots(page);

  await page.evaluate(() => {
    document
      .querySelectorAll('[data-testid="action-image-wrapper"] button, [data-testid="viewer-navigation-bar"]')
      .forEach((el) => el.style.setProperty("display", "none", "important"));
  });

  const meta = await page.evaluate(() => {
    const title =
      document.querySelector('[data-testid="document-title"], h1')?.innerText?.trim() ||
      document.title.replace("| Scribe", "").trim();
    const desc =
      document.querySelector('[data-testid="document-header"] p')?.innerText?.trim() || "";
    return {
      title,
      description: desc,
      stepCount: document.querySelectorAll('[data-testid="action-instruction"]').length,
    };
  });

  const stepCount = await page.$$eval(
    '[data-testid="action-instruction"]',
    (els) => els.length
  );
  if (!stepCount) {
    await page.pdf({
      path: dest,
      format: "Letter",
      printBackground: true,
      margin: { top: "0.45in", bottom: "0.45in", left: "0.5in", right: "0.5in" },
    });
    stripEmptyPages(dest);
    log(`OK ${guide.filename} (index, ${fs.statSync(dest).size} bytes)`);
    return "ok";
  }

  const shots = await captureAllSteps(page);
  if (!shots.length) throw new Error("No step screenshots captured");

  await page.setContent(buildPrintHtml(meta, shots), { waitUntil: "load" });
  await page.pdf({
    path: dest,
    format: "Letter",
    printBackground: true,
    margin: { top: "0.4in", bottom: "0.4in", left: "0.45in", right: "0.45in" },
  });
  stripEmptyPages(dest);
  log(`OK ${guide.filename} (${shots.length} steps, ${fs.statSync(dest).size} bytes)`);
  return "ok";
}

async function main() {
  fs.mkdirSync(OUT_DIR, { recursive: true });
  const guides = JSON.parse(fs.readFileSync(MANIFEST, "utf8"));
  const args = process.argv.slice(2);
  const force = args.includes("--force") || args.includes("-f");
  const filters = args.filter((a) => a !== "--force" && a !== "-f");
  const selected = filters.length
    ? guides.filter((g) =>
        filters.some(
          (s) =>
            g.filename.toLowerCase().includes(s.toLowerCase()) || g.url.includes(s)
        )
      )
    : guides;

  log(`Starting ${selected.length} guides force=${force}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
  });

  let page = await newPage(browser);
  const results = { ok: 0, skipped: 0, failed: 0 };

  for (const guide of selected) {
    let done = false;
    for (let attempt = 1; attempt <= 3 && !done; attempt++) {
      try {
        const status = await printOne(page, guide, { force });
        results[status === "skipped" ? "skipped" : "ok"] += 1;
        done = true;
      } catch (err) {
        log(`TRY ${attempt}/3 FAIL ${guide.filename}: ${err.message}`);
        try {
          await page.close();
        } catch {}
        page = await newPage(browser);
        if (attempt === 3) {
          results.failed += 1;
          log(`FAIL ${guide.filename}: ${err.message}`);
        } else {
          await new Promise((r) => setTimeout(r, 1500 * attempt));
        }
      }
    }
  }

  await browser.close();
  log(`Done ok=${results.ok} skipped=${results.skipped} failed=${results.failed}`);
  if (results.failed) process.exitCode = 1;
}

main().catch((err) => {
  log(`FATAL ${err.stack || err}`);
  process.exit(1);
});
