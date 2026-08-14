/**
 * Local guide site with login + editing.
 * Run: npm start
 * Open: http://127.0.0.1:8899
 */
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const { spawnSync } = require("child_process");
const express = require("express");
const session = require("express-session");
const cookieParser = require("cookie-parser");
const bcrypt = require("bcrypt");
const multer = require("multer");

const ROOT = __dirname;
const CONTENT_DIR = path.join(ROOT, "guide-content");
const IMAGE_ROOT = path.join(ROOT, "assets", "guides");
const AUTH = JSON.parse(fs.readFileSync(path.join(ROOT, "auth-config.json"), "utf8"));
const USERS = Array.isArray(AUTH.users)
  ? AUTH.users
  : AUTH.email
    ? [{ email: AUTH.email, passwordHash: AUTH.passwordHash, displayName: AUTH.displayName }]
    : [];
const PORT = Number(process.env.PORT || 8899);
const SESSION_SECRET =
  process.env.SESSION_SECRET ||
  crypto
    .createHash("sha256")
    .update(USERS.map((u) => u.passwordHash).join("|") || "dpm-guides")
    .digest("hex");

const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 12 * 1024 * 1024 },
  fileFilter(_req, file, cb) {
    if (/^image\/(jpeg|png|webp|gif)$/i.test(file.mimetype)) cb(null, true);
    else cb(new Error("Images only (jpeg, png, webp, gif)"));
  },
});

const app = express();
app.disable("x-powered-by");
app.use(cookieParser());
app.use(express.json({ limit: "4mb" }));
app.use(
  session({
    name: "dpm_guide_sid",
    secret: SESSION_SECRET,
    resave: false,
    saveUninitialized: false,
    cookie: {
      httpOnly: true,
      sameSite: "lax",
      maxAge: 1000 * 60 * 60 * 12,
    },
  })
);

function requireAuth(req, res, next) {
  if (req.session && req.session.user) return next();
  return res.status(401).json({ error: "Sign in required" });
}

function contentPath(slug) {
  const safe = String(slug || "").replace(/[^a-z0-9-]/gi, "");
  if (!safe || safe !== slug) return null;
  return path.join(CONTENT_DIR, `${safe}.json`);
}

function loadGuide(slug) {
  const file = contentPath(slug);
  if (!file || !fs.existsSync(file)) return null;
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

function renumberSteps(blocks) {
  let n = 0;
  return (blocks || []).map((b) => {
    if (b.kind !== "step") return { ...b, number: null };
    n += 1;
    return { ...b, number: n };
  });
}

function rebuildSite() {
  const result = spawnSync("python", ["build_site.py"], {
    cwd: ROOT,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    const msg = (result.stderr || result.stdout || "build failed").trim();
    throw new Error(msg.slice(0, 500));
  }
  return (result.stdout || "").trim().split("\n").slice(-3).join(" | ");
}

function syncManifest(guide) {
  const manifestPath = path.join(ROOT, "site-guides.json");
  if (!fs.existsSync(manifestPath)) return;
  const list = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const i = list.findIndex((g) => g.slug === guide.slug);
  if (i < 0) return;
  list[i] = {
    ...list[i],
    name: guide.name || guide.title || list[i].name,
    description: guide.description || "",
    tags: guide.tags || [],
    section: guide.section || list[i].section,
    subsection: guide.subsection ?? list[i].subsection,
  };
  fs.writeFileSync(manifestPath, JSON.stringify(list, null, 1), "utf8");
}

app.get("/api/me", (req, res) => {
  if (!req.session.user) return res.json({ authenticated: false });
  res.json({ authenticated: true, user: req.session.user });
});

app.post("/api/login", async (req, res) => {
  const email = String(req.body?.email || "")
    .trim()
    .toLowerCase();
  const password = String(req.body?.password || "");
  const account = USERS.find((u) => String(u.email || "").toLowerCase() === email);
  if (!account) {
    return res.status(401).json({ error: "Invalid email or password" });
  }
  const ok = await bcrypt.compare(password, account.passwordHash);
  if (!ok) return res.status(401).json({ error: "Invalid email or password" });
  req.session.user = {
    email: account.email,
    name: account.displayName || account.email,
  };
  res.json({ ok: true, user: req.session.user });
});

app.post("/api/logout", (req, res) => {
  req.session.destroy(() => {
    res.clearCookie("dpm_guide_sid");
    res.json({ ok: true });
  });
});

app.get("/api/guides/:slug", requireAuth, (req, res) => {
  const guide = loadGuide(req.params.slug);
  if (!guide) return res.status(404).json({ error: "Guide not found" });
  res.json(guide);
});

app.put("/api/guides/:slug", requireAuth, (req, res) => {
  const slug = req.params.slug;
  const existing = loadGuide(slug);
  if (!existing) return res.status(404).json({ error: "Guide not found" });

  const body = req.body || {};
  const title = String(body.title || "").trim();
  if (!title) return res.status(400).json({ error: "Title is required" });

  const tags = Array.isArray(body.tags)
    ? body.tags.map((t) => String(t).trim()).filter(Boolean)
    : String(body.tags || "")
        .split(",")
        .map((t) => t.trim())
        .filter(Boolean);

  const incoming = Array.isArray(body.blocks) ? body.blocks : [];
  const blocks = renumberSteps(
    incoming.map((b) => {
      const kind = ["step", "tip", "warning", "section"].includes(b.kind) ? b.kind : "step";
      const out = {
        kind,
        text: String(b.text || "").trim(),
        number: kind === "step" ? b.number || null : null,
      };
      if (kind === "step" && b.image && typeof b.image === "object") {
        out.image = b.image;
      }
      return out;
    })
  );

  if (!blocks.some((b) => b.kind === "step")) {
    return res.status(400).json({ error: "At least one step is required" });
  }

  const next = {
    ...existing,
    title,
    name: title,
    description: String(body.description || "").trim(),
    tags,
    section: body.section != null ? String(body.section) : existing.section,
    subsection:
      body.subsection === undefined
        ? existing.subsection
        : body.subsection === null || body.subsection === ""
          ? null
          : String(body.subsection),
    blocks,
    updatedAt: new Date().toISOString(),
    updatedBy: req.session.user.email,
  };

  fs.writeFileSync(contentPath(slug), JSON.stringify(next, null, 1), "utf8");
  syncManifest(next);

  try {
    const summary = rebuildSite();
    res.json({ ok: true, guide: next, rebuild: summary });
  } catch (err) {
    res.status(500).json({
      error: `Guide saved, but rebuild failed: ${err.message}`,
      guide: next,
    });
  }
});

app.post("/api/guides/:slug/image", requireAuth, upload.single("image"), (req, res) => {
  const slug = req.params.slug;
  const guide = loadGuide(slug);
  if (!guide) return res.status(404).json({ error: "Guide not found" });
  if (!req.file) return res.status(400).json({ error: "No image uploaded" });

  const stepIndex = Number(req.body?.stepIndex);
  if (!Number.isInteger(stepIndex) || stepIndex < 0) {
    return res.status(400).json({ error: "Invalid step index" });
  }

  const steps = (guide.blocks || []).filter((b) => b.kind === "step");
  if (stepIndex >= steps.length) return res.status(400).json({ error: "Step not found" });

  const ext = (req.file.mimetype.split("/")[1] || "jpeg").replace("jpeg", "jpeg");
  const dir = path.join(IMAGE_ROOT, slug);
  fs.mkdirSync(dir, { recursive: true });
  const filename = `step-${String(stepIndex + 1).padStart(2, "0")}-edit-${Date.now()}.${ext === "jpg" ? "jpeg" : ext}`;
  const abs = path.join(dir, filename);
  fs.writeFileSync(abs, req.file.buffer);
  const rel = path.posix.join("assets", "guides", slug, filename);

  let seen = 0;
  guide.blocks = (guide.blocks || []).map((b) => {
    if (b.kind !== "step") return b;
    if (seen++ !== stepIndex) return b;
    return {
      ...b,
      image: {
        ...(b.image || {}),
        file: rel,
        targets: [],
      },
    };
  });
  guide.updatedAt = new Date().toISOString();
  guide.updatedBy = req.session.user.email;
  fs.writeFileSync(contentPath(slug), JSON.stringify(guide, null, 1), "utf8");

  try {
    rebuildSite();
  } catch (err) {
    return res.status(500).json({ error: `Image saved, rebuild failed: ${err.message}`, file: rel });
  }
  res.json({ ok: true, file: rel, guide });
});

app.get(["/login", "/login.html"], (_req, res) => {
  res.sendFile(path.join(ROOT, "login.html"));
});

// The editor lives at the site root so its relative asset paths also work on
// the published copy, which has no route rewriting.
app.get(["/edit", "/edit.html"], (req, res) => {
  const slug = String(req.query.guide || "");
  if (!req.session.user) {
    return res.redirect(`/login.html?next=${encodeURIComponent(`edit.html?guide=${slug}`)}`);
  }
  res.sendFile(path.join(ROOT, "edit.html"));
});

app.get(["/edit/:slug", "/edit/:slug.html"], (req, res) => {
  res.redirect(`/edit.html?guide=${encodeURIComponent(req.params.slug)}`);
});

app.use(express.static(ROOT, { extensions: ["html"] }));

app.listen(PORT, "127.0.0.1", () => {
  console.log(`DPM Guides running at http://127.0.0.1:${PORT}`);
  console.log(`Editor accounts: ${USERS.map((u) => u.email).join(", ")}`);
});
