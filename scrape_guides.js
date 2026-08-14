/**
 * Scrape guide content for every entry in site-guides.json.
 *
 * ScribeHow's viewer renders lazily and zooms screenshots, so we load each page
 * with JavaScript disabled and read the server-rendered markup instead: it
 * contains every step, plain screenshot URLs, and click targets expressed as
 * percentages of the image. That markup is emitted twice (mobile + desktop
 * variants), so the duplicate pass is trimmed by watching the step numbering.
 *
 * Screenshots come from presigned S3 URLs that expire in ~15 minutes, so each
 * guide's images are downloaded right after its page is parsed.
 */
const fs = require("fs");
const path = require("path");
const puppeteer = require("puppeteer-core");

const ROOT = __dirname;
const MANIFEST = path.join(ROOT, "site-guides.json");
const CONTENT_DIR = path.join(ROOT, "guide-content");
const IMAGE_ROOT = path.join(ROOT, "assets", "guides");
const LOG = path.join(ROOT, "scrape-log.txt");
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";

function log(line) {
  const msg = `[${new Date().toISOString()}] ${line}`;
  console.log(msg);
  fs.appendFileSync(LOG, msg + "\n");
}

function toSharedUrl(url) {
  return url.includes("/viewer/") ? url.replace("/viewer/", "/shared/") : url;
}

async function newPage(browser) {
  const page = await browser.newPage();
  await page.setJavaScriptEnabled(false);
  await page.setViewport({ width: 1280, height: 1600 });
  await page.setUserAgent(UA);
  page.setDefaultNavigationTimeout(90000);
  return page;
}

async function extractGuide(page) {
  return page.evaluate(() => {
    const SELECTOR =
      '[data-testid="action-instruction"], [data-testid="action-tip-or-warning"], [data-testid="action-section"]';

    const cards = Array.from(document.querySelectorAll(SELECTOR));
    const blocks = [];

    for (const el of cards) {
      const testid = el.getAttribute("data-testid");

      if (testid === "action-section") {
        blocks.push({
          kind: "section",
          text: (el.innerText || "").replace(/\s+/g, " ").trim(),
        });
        continue;
      }

      if (testid === "action-tip-or-warning") {
        const cls = el.className || "";
        blocks.push({
          kind: /warning|danger|error/i.test(cls) ? "warning" : "tip",
          text: (el.innerText || "").replace(/\s+/g, " ").trim(),
        });
        continue;
      }

      const wrapper = el.querySelector('[data-testid="action-image-wrapper"]');
      const clone = el.cloneNode(true);
      clone.querySelectorAll('[data-testid="action-image-wrapper"]').forEach((n) => n.remove());

      // The leading span holds the step number; pull it out before reading text.
      let ordinal = null;
      const spans = clone.querySelectorAll("span");
      for (const span of spans) {
        const t = (span.innerText || "").trim();
        if (/^\d+$/.test(t)) {
          ordinal = parseInt(t, 10);
          span.remove();
          break;
        }
      }
      const text = (clone.innerText || "").replace(/\s+/g, " ").trim();

      let image = null;
      if (wrapper) {
        const img = wrapper.querySelector("img");
        const src = img ? img.getAttribute("src") || "" : "";
        if (src) {
          const targets = Array.from(
            wrapper.querySelectorAll('[data-testid="action-click-target"]')
          ).map((t) => ({
            style: t.getAttribute("style") || "",
            round: /rounded-full/.test(t.className || ""),
          }));
          const wrapStyle = wrapper.getAttribute("style") || "";
          const ratio = /aspect-ratio:\s*([^;]+)/i.exec(wrapStyle);
          image = {
            src,
            aspectRatio: ratio ? ratio[1].trim() : "",
            targets: targets.filter((t) => /%/.test(t.style)),
          };
        }
      }

      blocks.push({
        kind: "step",
        number: ordinal === null ? null : ordinal,
        text,
        image,
      });
    }

    // The page ships the entire action list twice (mobile + desktop variants).
    // Drop the repeat when the two halves match, else cut at the ordinal reset.
    const signature = (b) => `${b.kind}|${b.number || ""}|${b.text}`;
    let unique = blocks;
    const half = blocks.length / 2;
    if (
      blocks.length > 1 &&
      blocks.length % 2 === 0 &&
      blocks
        .slice(0, half)
        .every((b, i) => signature(b) === signature(blocks[half + i]))
    ) {
      unique = blocks.slice(0, half);
    } else {
      const seen = new Set();
      const cut = [];
      for (const b of blocks) {
        if (b.kind === "step" && b.number !== null) {
          if (seen.has(b.number)) break;
          seen.add(b.number);
        }
        cut.push(b);
      }
      // A trailing tip/section belongs to the repeated pass, not this one.
      while (cut.length && cut[cut.length - 1].kind !== "step") cut.pop();
      unique = cut;
    }

    const titleEl = document.querySelector('[data-testid="document-title"], h1');
    return {
      title: (titleEl?.innerText || document.title.replace(/\s*\|\s*Scribe.*$/i, "")).trim(),
      blocks: unique,
    };
  });
}

/** Read pixel dimensions straight from a PNG/JPEG buffer. */
function imageSize(buf) {
  if (buf.length > 24 && buf.readUInt32BE(0) === 0x89504e47) {
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
  }
  if (buf.length > 4 && buf[0] === 0xff && buf[1] === 0xd8) {
    let offset = 2;
    while (offset + 9 < buf.length) {
      if (buf[offset] !== 0xff) {
        offset += 1;
        continue;
      }
      const marker = buf[offset + 1];
      const length = buf.readUInt16BE(offset + 2);
      if (marker >= 0xc0 && marker <= 0xcf && ![0xc4, 0xc8, 0xcc].includes(marker)) {
        return { height: buf.readUInt16BE(offset + 5), width: buf.readUInt16BE(offset + 7) };
      }
      offset += 2 + length;
    }
  }
  return null;
}

async function download(url, dest, attempts = 3) {
  for (let i = 1; i <= attempts; i++) {
    try {
      const res = await fetch(url, { headers: { "User-Agent": UA } });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const buf = Buffer.from(await res.arrayBuffer());
      if (buf.length < 500) throw new Error(`tiny response (${buf.length} bytes)`);
      fs.writeFileSync(dest, buf);
      return { bytes: buf.length, size: imageSize(buf) };
    } catch (err) {
      if (i === attempts) throw err;
      await new Promise((r) => setTimeout(r, 800 * i));
    }
  }
}

function extFor(url) {
  const m = /\.(png|jpe?g|webp|gif)(?:\?|$)/i.exec(url);
  return m ? `.${m[1].toLowerCase().replace(/^jpg$/, "jpeg")}` : ".jpeg";
}

function contentComplete(contentPath) {
  if (!fs.existsSync(contentPath)) return false;
  try {
    const prev = JSON.parse(fs.readFileSync(contentPath, "utf8"));
    if (!prev.blocks || !prev.blocks.length) return false;
    return !prev.blocks.some(
      (b) => b.image && b.image.file && !fs.existsSync(path.join(ROOT, b.image.file))
    );
  } catch {
    return false;
  }
}

async function scrapeOne(page, guide, { force }) {
  const contentPath = path.join(CONTENT_DIR, `${guide.slug}.json`);
  if (!force && contentComplete(contentPath)) {
    log(`SKIP ${guide.slug}`);
    return "skipped";
  }

  const url = toSharedUrl(guide.url);
  const resp = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
  if (resp && resp.status() >= 400) throw new Error(`HTTP ${resp.status()}`);
  await page.waitForSelector('[data-testid="action-instruction"], h1', { timeout: 30000 });

  const data = await extractGuide(page);
  const steps = data.blocks.filter((b) => b.kind === "step");
  if (!steps.length) throw new Error("no steps found");

  const imgDir = path.join(IMAGE_ROOT, guide.slug);
  fs.mkdirSync(imgDir, { recursive: true });

  let bytes = 0;
  let shots = 0;
  const seen = new Map();
  let index = 0;
  for (const block of data.blocks) {
    if (block.kind !== "step") continue;
    index += 1;
    if (!block.image || !block.image.src) continue;
    const src = block.image.src;
    if (seen.has(src)) {
      Object.assign(block.image, seen.get(src));
      delete block.image.src;
      continue;
    }
    const name = `step-${String(index).padStart(2, "0")}${extFor(src)}`;
    const rel = path.posix.join("assets", "guides", guide.slug, name);
    const { bytes: n, size } = await download(src, path.join(imgDir, name));
    bytes += n;
    const info = { file: rel };
    if (size) {
      info.width = size.width;
      info.height = size.height;
      if (!block.image.aspectRatio) info.aspectRatio = `${size.width} / ${size.height}`;
    }
    Object.assign(block.image, info);
    delete block.image.src;
    seen.set(src, info);
    shots += 1;
  }

  const out = {
    slug: guide.slug,
    name: guide.name,
    title: data.title || guide.name,
    description: guide.description || "",
    section: guide.section,
    subsection: guide.subsection,
    pdf: guide.pdf,
    tags: guide.tags,
    sourceUrl: url,
    scrapedAt: new Date().toISOString(),
    blocks: data.blocks,
  };
  fs.writeFileSync(contentPath, JSON.stringify(out, null, 1), "utf8");

  const extras = data.blocks.filter((b) => b.kind !== "step").map((b) => b.kind);
  log(
    `OK ${guide.slug}: ${steps.length} steps, ${shots} images, ${Math.round(bytes / 1024)} KB` +
      (extras.length ? ` [${extras.join(",")}]` : "") +
      (steps.some((s) => !s.image) ? " (text-only steps present)" : "")
  );
  return "ok";
}

async function main() {
  fs.mkdirSync(CONTENT_DIR, { recursive: true });
  fs.mkdirSync(IMAGE_ROOT, { recursive: true });
  const guides = JSON.parse(fs.readFileSync(MANIFEST, "utf8")).filter((g) => g.url);
  const args = process.argv.slice(2);
  const force = args.includes("--force") || args.includes("-f");
  const filters = args.filter((a) => !a.startsWith("-"));
  const selected = filters.length
    ? guides.filter((g) =>
        filters.some((f) => g.slug.includes(f.toLowerCase()) || g.url.includes(f))
      )
    : guides;

  log(`Scraping ${selected.length} guides force=${force}`);
  const browser = await puppeteer.launch({
    executablePath: CHROME,
    headless: "new",
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--hide-scrollbars"],
  });

  let page = await newPage(browser);
  const tally = { ok: 0, skipped: 0, failed: 0 };
  const failures = [];

  for (const guide of selected) {
    let done = false;
    for (let attempt = 1; attempt <= 3 && !done; attempt++) {
      try {
        const status = await scrapeOne(page, guide, { force });
        tally[status === "skipped" ? "skipped" : "ok"] += 1;
        done = true;
      } catch (err) {
        log(`TRY ${attempt}/3 FAIL ${guide.slug}: ${err.message}`);
        try {
          await page.close();
        } catch {}
        page = await newPage(browser);
        if (attempt === 3) {
          tally.failed += 1;
          failures.push(`${guide.slug}: ${err.message}`);
        } else {
          await new Promise((r) => setTimeout(r, 1500 * attempt));
        }
      }
    }
  }

  await browser.close();
  log(`Done ok=${tally.ok} skipped=${tally.skipped} failed=${tally.failed}`);
  failures.forEach((f) => log(`FAILED ${f}`));
  if (tally.failed) process.exitCode = 1;
}

main().catch((err) => {
  log(`FATAL ${err.stack || err}`);
  process.exit(1);
});
