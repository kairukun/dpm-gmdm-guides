"""Build the Dossani Paradise Management guides website from cached ScribeHow data."""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PDF_ROOT = ROOT / "pdfs"
CONTENT_DIR = ROOT / "guide-content"
GUIDE_DIR = ROOT / "guides"
DATA_DIR = ROOT / "data"
TEMP = Path.home() / "AppData/Local/Temp"
ASSET_SRC = Path(
    r"C:\Users\James\.cursor\projects\c-Users-James-Documents-Ampler-GMDM-Guide-PDFs\assets"
)
LOGO_SRC = ASSET_SRC / (
    "c__Users_James_AppData_Roaming_Cursor_User_workspaceStorage_"
    "acfbfada168b8a84b78bf716f3b35741_images_dpm-lockup-740c0f57-fc8b-48d5-97bc-8ea2bff772ee.png"
)
BG_SRC = ASSET_SRC / (
    "c__Users_James_AppData_Roaming_Cursor_User_workspaceStorage_"
    "acfbfada168b8a84b78bf716f3b35741_images_Dossani-Paradise-O365-bg-only-"
    "fef9e01b-e6e2-4f2c-8410-47bd166306f5.png"
)

# Sections/guides the client asked to drop
EXCLUDED_SUBSECTIONS = {"isolved", "owlops", "ampler"}
EXCLUDED_GUIDES = {"setting up ampler command station"}
# Kept guides can still carry app tags for the dropped systems
EXCLUDED_TAGS = {"isolved", "owlops"}

CONTACT_EMAIL = "kyle@dossaniparadise.com"


# Some cached ScribeHow copy came through as UTF-8 bytes read as cp1252
MOJIBAKE = re.compile(r"[âÂãÃ][\u0080-\u009f\u00a0-\u00bf\u2013-\u2122]")


def fix_text(value: str) -> str:
    if not value or not MOJIBAKE.search(value):
        return value
    try:
        repaired = value.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return value if "\ufffd" in repaired else repaired


def texts(node, out=None):
    if out is None:
        out = []
    if isinstance(node, dict):
        if node.get("text"):
            out.append(node["text"])
        for v in node.values():
            texts(v, out)
    elif isinstance(node, list):
        for v in node:
            texts(v, out)
    return out


def load_next_data(name: str) -> dict:
    """Prefer the copy committed to the repo so the build also runs in CI."""
    for candidate in (DATA_DIR / name, TEMP / name):
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8-sig"))
    raise FileNotFoundError(f"Missing source data: {name}")


def doc_index(data: dict) -> dict:
    """Map document id -> metadata (description, step count, app tags)."""
    out = {}
    result = data["props"]["pageProps"]["result"]
    pools = [result.get("scribe_documents") or []]
    embedded = result.get("embedded_documents") or {}
    if isinstance(embedded, dict):
        pools.append(list(embedded.values()))
    for pool in pools:
        for doc in pool:
            if isinstance(doc, dict) and doc.get("id"):
                out.setdefault(doc["id"], doc)
    return out


def normalize_url(url: str) -> str:
    return (url or "").split("?")[0].rstrip("/")


def collect(data: dict, default_section: str | None = None) -> list[dict]:
    blocks = data["props"]["pageProps"]["result"]["editor_js_data"]["content"]
    docs = doc_index(data)
    section = default_section
    subsection = None
    items = []
    for block in blocks:
        btype = block.get("type")
        attrs = block.get("attrs") or {}
        if btype == "heading":
            level = attrs.get("level") or 2
            title = " ".join(texts(block)).strip()
            if level <= 2:
                section, subsection = title, None
            else:
                subsection = title
            continue
        if btype != "IncludeScribeExtension":
            continue
        scribe = attrs.get("scribe") or {}
        doc = docs.get(scribe.get("id")) or {}
        name = (scribe.get("name") or doc.get("name") or "").strip()
        url = normalize_url(attrs.get("scribeUrl") or scribe.get("documentUrl") or "")
        if not url:
            # The source page uses placeholder blocks for guides that aren't published yet
            placeholder = (attrs.get("placeholderText") or "").strip()
            if attrs.get("showPlaceholder") and placeholder:
                items.append(
                    {
                        "name": placeholder,
                        "url": "",
                        "section": section,
                        "subsection": subsection,
                        "description": "",
                        "steps": 0,
                        "tags": [],
                        "pdf": None,
                    }
                )
            continue
        if not name:
            continue
        items.append(
            {
                "name": fix_text(name),
                "url": url,
                "section": section,
                "subsection": subsection,
                "description": fix_text((doc.get("description") or "").strip()),
                "steps": doc.get("actions_count") or 0,
                "tags": [
                    t["name"]
                    for t in (doc.get("app_tags") or [])
                    if t.get("name") and t["name"].strip().lower() not in EXCLUDED_TAGS
                ],
            }
        )
    return items


def pdf_lookup() -> dict:
    """Map normalized guide name -> relative pdf path."""
    out = {}
    for pdf in PDF_ROOT.rglob("*.pdf"):
        key = pdf.stem.lower()
        out[key] = pdf.relative_to(ROOT).as_posix()
    return out


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def match_pdf(guide: dict, manifest: list[dict], pdfs: dict) -> str | None:
    for entry in manifest:
        if normalize_url(entry["url"]) == guide["url"] or entry["name"].strip().lower() == guide["name"].lower():
            key = Path(entry["filename"]).stem.lower()
            if key in pdfs:
                return pdfs[key]
    key = slug(guide["name"])
    for name, rel in pdfs.items():
        if slug(name) == key:
            return rel
    return None


def build_groups() -> list[dict]:
    manifest = json.loads((ROOT / "guides.json").read_text(encoding="utf-8"))
    pdfs = pdf_lookup()

    items = collect(load_next_data("scribe-next-data.json"))
    par_items = collect(load_next_data("scribe-par-next.json"), default_section="PAR POS Guides")
    for it in par_items:
        it["section"] = "PAR POS Guides"
        it["subsection"] = None
    items.extend(par_items)

    seen_urls = set()
    groups: dict[tuple[str, str | None], dict] = {}
    for it in items:
        section = it["section"] or "Guides"
        sub = it["subsection"]
        if (sub or "").strip().lower() in EXCLUDED_SUBSECTIONS:
            continue
        if it["name"].strip().lower() in EXCLUDED_GUIDES:
            continue
        if it["url"]:
            if it["url"] in seen_urls:
                continue
            seen_urls.add(it["url"])
            it["pdf"] = match_pdf(it, manifest, pdfs)
        else:
            it["pdf"] = None
        key = (section, sub)
        groups.setdefault(key, {"section": section, "subsection": sub, "guides": []})
        groups[key]["guides"].append(it)

    order = ["PAR POS Guides", "Office ScribeHows", "Equipment ScribeHows"]
    result = []
    for section in order:
        subs = [g for k, g in groups.items() if k[0] == section]
        subs.sort(key=lambda g: (g["subsection"] or "").lower())
        for g in subs:
            g["guides"].sort(key=lambda x: x["name"].lower())
            result.append(g)
    for key, g in groups.items():
        if key[0] not in order:
            g["guides"].sort(key=lambda x: x["name"].lower())
            result.append(g)

    used = set()
    for group in result:
        for guide in group["guides"]:
            base = slug(guide["name"]) or "guide"
            candidate, n = base, 2
            while candidate in used:
                candidate, n = f"{base}-{n}", n + 1
            used.add(candidate)
            guide["slug"] = candidate
    return result


def card_html(guide: dict) -> str:
    name = html.escape(guide["name"])
    desc = html.escape(guide["description"])
    if not guide["url"]:
        return f"""            <article class="card card-pending" data-name="{name.lower()}" data-desc="">
              <h3 class="card-title">{name}</h3>
              <div class="card-meta"><span class="meta-item">Coming soon</span></div>
            </article>"""
    meta = []
    if guide["steps"]:
        meta.append(f'<span class="meta-item">{guide["steps"]} steps</span>')
    tags = "".join(
        f'<span class="tag">{html.escape(t)}</span>' for t in dict.fromkeys(guide["tags"])
    )
    if guide.get("page"):
        open_link = f'<a class="btn btn-primary" href="{html.escape(guide["page"])}">Open guide</a>'
        edit_link = (
            f'<a class="btn btn-edit auth-only" href="edit/{html.escape(guide["slug"])}" hidden>Edit</a>'
        )
    else:
        open_link = '<span class="btn btn-disabled">Guide page pending</span>'
        edit_link = ""
    return f"""            <article class="card" data-name="{name.lower()}" data-desc="{desc.lower()}" data-slug="{html.escape(guide.get('slug') or '')}">
              <h3 class="card-title">{name}</h3>
              {f'<p class="card-desc">{desc}</p>' if desc else ''}
              <div class="card-tags">{tags}</div>
              <div class="card-meta">{''.join(meta)}</div>
              <div class="card-actions">
                {open_link}
                {edit_link}
              </div>
            </article>"""


def section_html(groups: list[dict]) -> tuple[str, str]:
    body = []
    nav = []
    current_section = None
    for group in groups:
        if group["section"] != current_section:
            if current_section is not None:
                body.append("      </section>")
            current_section = group["section"]
            sid = slug(current_section)
            nav.append(f'<a class="nav-link" href="#{sid}">{html.escape(current_section)}</a>')
            body.append(f'      <section class="section" id="{sid}">')
            body.append(f'        <h2 class="section-title">{html.escape(current_section)}</h2>')
        if group["subsection"]:
            gid = slug(f'{current_section}-{group["subsection"]}')
            body.append(f'        <div class="group" id="{gid}">')
            body.append(
                f'          <h3 class="group-title">{html.escape(group["subsection"])}'
                f'<span class="group-count">{len(group["guides"])}</span></h3>'
            )
        else:
            body.append('        <div class="group">')
        body.append('          <div class="cards">')
        body.extend(card_html(g) for g in group["guides"])
        body.append("          </div>")
        body.append("        </div>")
    if current_section is not None:
        body.append("      </section>")
    return "\n".join(body), "\n            ".join(nav)


def build_html(groups: list[dict]) -> str:
    sections, nav = section_html(groups)
    total = sum(1 for g in groups for x in g["guides"] if x["url"])
    categories = len({g["section"] for g in groups})
    systems = len({g["subsection"] for g in groups if g["subsection"]})
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dossani Paradise Management | GM/DM Guides</title>
  <meta name="description" content="Step-by-step GM and DM operating guides for Dossani Paradise Management restaurants.">
  <link rel="stylesheet" href="assets/styles.css">
</head>
<body>
  <header class="hero">
    <div class="hero-inner">
      <img class="hero-logo" src="assets/dpm-lockup.png" alt="Dossani Paradise Management">
      <h1 class="hero-title">GM / DM Guides</h1>
      <p class="hero-sub">
        Step-by-step walkthroughs for the systems your restaurant runs on.
        Open a guide for training and day-to-day reference.
      </p>
      <div class="hero-stats">
        <div class="stat"><span class="stat-num">{total}</span><span class="stat-label">Guides</span></div>
        <div class="stat"><span class="stat-num">{systems}</span><span class="stat-label">Systems</span></div>
        <div class="stat"><span class="stat-num">{categories}</span><span class="stat-label">Categories</span></div>
      </div>
    </div>
  </header>

  <nav class="subnav">
    <div class="subnav-inner">
      <div class="nav-links">
            {nav}
      </div>
      <div class="subnav-right">
        <label class="search">
          <input type="search" id="guide-search" placeholder="Search guides..." autocomplete="off">
        </label>
        <div class="auth-slot" data-auth-slot hidden>
          <a class="nav-link" href="login.html">Editor sign in</a>
        </div>
      </div>
    </div>
  </nav>

  <main class="wrap">
    <p class="notice">
      Please email <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> with any suggestions for these
      guides or any mistakes you see in the instructions.
    </p>
    <p class="empty-state" id="empty-state" hidden>No guides match your search.</p>

{sections}
  </main>

  <footer class="footer">
    <img class="footer-logo" src="assets/dpm-lockup.png" alt="Dossani Paradise Management">
    <p>&copy; Dossani Paradise Management &mdash; internal training reference.</p>
  </footer>

  <script src="assets/site.js"></script>
</body>
</html>
"""


def scribe_key(url: str) -> str:
    """Last path segment of a ScribeHow url, which is stable across /shared/ and /viewer/."""
    return normalize_url(url).rsplit("/", 1)[-1].lower()


def rich_text(raw: str, link_map: dict[str, str]) -> str:
    """Convert ScribeHow's markdown-ish step text to HTML, keeping links internal."""
    text = html.escape(fix_text(raw or ""))

    def resolve_local(target: str, label: str) -> str | None:
        key = scribe_key(target)
        by_url = link_map.get(key)
        by_label = link_map.get(f"name:{slug(label)}") if label else None
        # Prefer the label when the source URL pointed at the wrong guide.
        if by_label and by_url and by_label != by_url:
            return by_label
        return by_label or by_url

    def link(target: str, label: str) -> str:
        target = html.unescape(target).strip()
        label_html = label
        if target.lower().startswith("mailto:"):
            addr = target.split(":", 1)[1]
            if addr.lower().endswith("@amplergroup.com"):
                addr = CONTACT_EMAIL
                label_html = html.escape(CONTACT_EMAIL) if "@" in html.unescape(label) else label
            return f'<a href="mailto:{html.escape(addr)}">{label_html}</a>'
        if target.endswith(".html") and "://" not in target:
            return f'<a href="{html.escape(target)}">{label_html}</a>'
        if "scribehow.com" in target.lower():
            local = resolve_local(target, html.unescape(label))
            if local:
                return f'<a href="{html.escape(local)}">{label_html}</a>'
            return label_html
        local = resolve_local(target, html.unescape(label))
        if local:
            return f'<a href="{html.escape(local)}">{label_html}</a>'
        if target.lower().startswith(("http://", "https://")):
            return f'<a href="{html.escape(target)}" target="_blank" rel="noopener">{label_html}</a>'
        return label_html

    text = re.sub(
        r"\[([^\]]+)\]\(([^)\s]+)\)",
        lambda m: link(m.group(2), m.group(1)),
        text,
    )
    # Bare urls that were not already turned into anchors
    text = re.sub(
        r'(?<!href=")(?<!>)(https?://[^\s<)]+)(?![^<]*</a>)',
        lambda m: link(m.group(1), m.group(1)),
        text,
    )
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # Soft-fix missing spaces around anchors from the source copy
    text = re.sub(r"(</a>)([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z:])(<a\s)", r"\1 \2", text)
    return text


def overlay_html(overlay: dict) -> str:
    """Rebuild a ScribeHow click indicator from its percentage-based inline style."""
    style = overlay.get("style", "")
    keep = []
    color = "#22c55e"
    for part in style.split(";"):
        if ":" not in part:
            continue
        prop, value = (p.strip() for p in part.split(":", 1))
        prop_l = prop.lower()
        if prop_l in {"width", "height", "left", "top"}:
            keep.append(f"{prop_l}:{value}")
        elif prop_l == "border-color":
            color = value
    if not keep:
        return ""
    shape = "overlay-circle" if overlay.get("round", True) else "overlay-rect"
    keep.append(f"border-color:{color}")
    return f'<span class="overlay {shape}" style="{html.escape(";".join(keep))}"></span>'


def block_html(block: dict, prefix: str, link_map: dict[str, str], eager: bool) -> str:
    kind = block.get("kind")
    body = rich_text(block.get("text") or "", link_map)

    if kind == "section":
        return f'        <li class="step-section"><h2>{body}</h2></li>'

    if kind in {"tip", "warning"}:
        label = "Warning" if kind == "warning" else "Tip"
        return f"""        <li class="note note-{kind}">
          <span class="note-label">{label}</span>
          <div class="note-text">{body}</div>
        </li>"""

    number = block.get("number") or 0
    image = block.get("image") or {}
    figure = ""
    if image.get("file"):
        ratio = image.get("aspectRatio") or ""
        if not ratio and image.get("width") and image.get("height"):
            ratio = f'{image["width"]} / {image["height"]}'
        style = f' style="aspect-ratio:{html.escape(ratio)}"' if ratio else ""
        overlays = "".join(overlay_html(o) for o in image.get("targets") or [])
        src = html.escape(prefix + image["file"])
        dims = ""
        if image.get("width") and image.get("height"):
            dims = f' width="{image["width"]}" height="{image["height"]}"'
        loading = "eager" if eager else "lazy"
        figure = f"""
          <figure class="step-shot"{style}>
            <img src="{src}" alt="Screenshot for step {number}"{dims} loading="{loading}" decoding="async">
            {overlays}
          </figure>"""
    return f"""        <li class="step" id="step-{number}">
          <div class="step-head">
            <span class="step-num">{number}</span>
            <div class="step-text">{body}</div>
          </div>{figure}
        </li>"""


def guide_page_html(
    guide: dict,
    content: dict,
    prev: dict | None,
    nxt: dict | None,
    link_map: dict[str, str],
) -> str:
    up = "../"
    title = html.escape(content.get("title") or guide["name"])
    desc = html.escape(content.get("description") or guide["description"] or "")
    crumb = " / ".join(
        html.escape(x) for x in [guide["section"], guide["subsection"]] if x
    )
    blocks = content.get("blocks") or []
    steps = [b for b in blocks if b.get("kind") == "step"]
    shots = sum(1 for s in steps if (s.get("image") or {}).get("file"))
    tags = "".join(
        f'<span class="tag">{html.escape(t)}</span>' for t in dict.fromkeys(guide["tags"])
    )

    def nav_link(other: dict | None, label: str, cls: str) -> str:
        if not other:
            return '<span class="pager-slot"></span>'
        return (
            f'<a class="pager {cls}" href="{html.escape(other["slug"])}.html">'
            f'<span class="pager-label">{label}</span>'
            f'<span class="pager-name">{html.escape(other["name"])}</span></a>'
        )

    steps_markup = "\n".join(
        block_html(b, up, link_map, eager=(i < 2)) for i, b in enumerate(blocks)
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} | Dossani Paradise Management</title>
  <meta name="description" content="{desc}">
  <link rel="stylesheet" href="{up}assets/styles.css">
</head>
<body class="guide-body">
  <header class="guide-bar">
    <div class="guide-bar-inner">
      <a class="guide-back" href="{up}index.html">All guides</a>
      <div class="guide-bar-right">
        <div class="auth-slot" data-auth-slot data-edit-slug="{html.escape(guide["slug"])}" hidden>
          <a class="nav-link" href="{up}login.html">Editor sign in</a>
        </div>
        <img class="guide-bar-logo" src="{up}assets/dpm-lockup.png" alt="Dossani Paradise Management">
      </div>
    </div>
  </header>

  <div class="guide-hero">
    <div class="guide-hero-inner">
      <p class="guide-crumb">{crumb}</p>
      <h1 class="guide-title">{title}</h1>
      {f'<p class="guide-desc">{desc}</p>' if desc else ''}
      <div class="guide-tags">{tags}</div>
      <div class="guide-actions">
        <span class="guide-count">{len(steps)} steps &middot; {shots} screenshots</span>
      </div>
    </div>
  </div>

  <main class="guide-wrap">
    <ol class="steps">
{steps_markup}
    </ol>

    <nav class="pager-row">
      {nav_link(prev, "Previous", "pager-prev")}
      {nav_link(nxt, "Next", "pager-next")}
    </nav>
  </main>

  <footer class="footer">
    <img class="footer-logo" src="{up}assets/dpm-lockup.png" alt="Dossani Paradise Management">
    <p>&copy; Dossani Paradise Management &mdash; internal training reference.</p>
  </footer>

  <a class="to-top" href="#" aria-label="Back to top">&uarr;</a>
  <script src="{up}assets/site.js"></script>
</body>
</html>
"""


CSS = """:root {
  --navy: #1b1f6b;
  --navy-deep: #0d1240;
  --red: #e2001a;
  --ink: #131a33;
  --muted: #5b6480;
  --line: #e3e7f2;
  --surface: #ffffff;
  --page: #f4f6fc;
}

* { box-sizing: border-box; }

/* Keeps [hidden] winning over layout rules like .auth-slot { display: flex }. */
[hidden] { display: none !important; }

body {
  margin: 0;
  font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
  color: var(--ink);
  background: var(--page);
  line-height: 1.55;
}

img { max-width: 100%; }

a { color: var(--navy); }

.wrap {
  max-width: 1180px;
  margin: 0 auto;
  padding: 0 24px 72px;
}

/* Hero */
.hero {
  position: relative;
  background-image: url("dossani-paradise-bg.png");
  background-size: cover;
  background-position: center;
  color: #fff;
  border-bottom: 5px solid var(--red);
}

.hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(9, 13, 48, 0.35) 0%, rgba(9, 13, 48, 0.72) 100%);
}

.hero-inner {
  position: relative;
  z-index: 1;
  max-width: 1180px;
  margin: 0 auto;
  padding: 64px 24px 72px;
  text-align: center;
}

.hero-logo {
  width: 340px;
  max-width: 78%;
  background: #fff;
  padding: 16px 24px;
  border-radius: 14px;
  box-shadow: 0 18px 44px rgba(0, 0, 0, 0.32);
}

.hero-title {
  margin: 34px 0 12px;
  font-size: clamp(2.1rem, 5vw, 3.2rem);
  letter-spacing: 0.5px;
  text-transform: uppercase;
}

.hero-sub {
  margin: 0 auto;
  max-width: 640px;
  font-size: 1.05rem;
  color: rgba(255, 255, 255, 0.88);
}

.hero-stats {
  display: flex;
  justify-content: center;
  gap: 18px;
  flex-wrap: wrap;
  margin-top: 34px;
}

.stat {
  min-width: 118px;
  padding: 14px 20px;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.24);
  backdrop-filter: blur(4px);
}

.stat-num {
  display: block;
  font-size: 1.8rem;
  font-weight: 700;
}

.stat-label {
  font-size: 0.78rem;
  letter-spacing: 1.4px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.82);
}

/* Sub navigation */
.subnav {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(255, 255, 255, 0.96);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(8px);
}

.subnav-inner {
  max-width: 1180px;
  margin: 0 auto;
  padding: 12px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.subnav-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.auth-slot { display: flex; align-items: center; gap: 8px; }

.btn-edit {
  background: #fff;
  color: var(--navy);
  border: 1px solid rgba(27, 31, 107, 0.35);
}

.btn-edit:hover {
  background: var(--navy);
  color: #fff;
  border-color: var(--navy);
}

.guide-bar-right {
  display: flex;
  align-items: center;
  gap: 14px;
}

.nav-links {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.nav-link {
  padding: 8px 14px;
  border-radius: 999px;
  font-size: 0.9rem;
  font-weight: 600;
  text-decoration: none;
  color: var(--navy);
  border: 1px solid var(--line);
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.nav-link:hover {
  background: var(--navy);
  border-color: var(--navy);
  color: #fff;
}

.search input {
  width: 260px;
  max-width: 100%;
  padding: 9px 14px;
  font: inherit;
  font-size: 0.92rem;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: #fff;
  color: var(--ink);
}

.search input:focus {
  outline: none;
  border-color: var(--navy);
  box-shadow: 0 0 0 3px rgba(27, 31, 107, 0.12);
}

/* Content */
.notice {
  margin: 32px 0 8px;
  padding: 14px 18px;
  background: #fff;
  border-left: 4px solid var(--red);
  border-radius: 8px;
  font-size: 0.95rem;
  color: var(--muted);
  box-shadow: 0 1px 3px rgba(19, 26, 51, 0.06);
}

.empty-state {
  margin: 28px 0;
  padding: 18px;
  text-align: center;
  color: var(--muted);
  background: #fff;
  border: 1px dashed var(--line);
  border-radius: 10px;
}

.section { margin-top: 44px; scroll-margin-top: 84px; }

.section-title {
  margin: 0 0 6px;
  font-size: 1.75rem;
  color: var(--navy-deep);
  padding-bottom: 12px;
  border-bottom: 3px solid var(--red);
}

.group { margin-top: 28px; scroll-margin-top: 84px; }

.group-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 14px;
  font-size: 1.1rem;
  text-transform: uppercase;
  letter-spacing: 1.1px;
  color: var(--navy);
}

.group-count {
  padding: 2px 9px;
  border-radius: 999px;
  background: var(--navy);
  color: #fff;
  font-size: 0.72rem;
  letter-spacing: 0.5px;
}

.cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(298px, 1fr));
  gap: 18px;
}

.card {
  display: flex;
  flex-direction: column;
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 1px 2px rgba(19, 26, 51, 0.05);
  transition: transform 0.15s, box-shadow 0.15s, border-color 0.15s;
}

.card:hover {
  transform: translateY(-3px);
  border-color: rgba(27, 31, 107, 0.35);
  box-shadow: 0 14px 30px rgba(19, 26, 51, 0.12);
}

.card-title {
  margin: 0 0 8px;
  font-size: 1.06rem;
  line-height: 1.35;
  color: var(--navy-deep);
}

.card-desc {
  margin: 0 0 12px;
  font-size: 0.9rem;
  color: var(--muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.tag {
  padding: 3px 9px;
  border-radius: 999px;
  background: #eef1fa;
  color: var(--navy);
  font-size: 0.72rem;
  font-weight: 600;
}

.card-meta {
  display: flex;
  gap: 14px;
  margin-bottom: 14px;
  font-size: 0.78rem;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.meta-pdf { color: var(--red); font-weight: 600; }

.card-pending {
  background: #fbfcff;
  border-style: dashed;
  box-shadow: none;
}

.card-pending:hover { transform: none; box-shadow: none; }

.card-pending .card-title { color: var(--muted); }

.card-actions {
  display: flex;
  gap: 10px;
  margin-top: auto;
  flex-wrap: wrap;
}

.btn {
  padding: 9px 16px;
  border-radius: 999px;
  font-size: 0.86rem;
  font-weight: 600;
  text-decoration: none;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}

.btn-primary {
  background: var(--navy);
  color: #fff;
  border: 1px solid var(--navy);
}

.btn-primary:hover { background: var(--navy-deep); }

.btn-ghost {
  background: #fff;
  color: var(--red);
  border: 1px solid rgba(226, 0, 26, 0.4);
}

.btn-ghost:hover { background: var(--red); color: #fff; border-color: var(--red); }

.btn-disabled {
  background: #f1f3f9;
  color: #9aa2b8;
  border: 1px solid var(--line);
  cursor: not-allowed;
}

/* ---------- Guide pages ---------- */
.guide-bar {
  position: sticky;
  top: 0;
  z-index: 30;
  background: rgba(255, 255, 255, 0.97);
  border-bottom: 1px solid var(--line);
  backdrop-filter: blur(8px);
}

.guide-bar-inner {
  max-width: 940px;
  margin: 0 auto;
  padding: 10px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.guide-back {
  padding: 7px 15px 7px 12px;
  border: 1px solid var(--line);
  border-radius: 999px;
  font-size: 0.88rem;
  font-weight: 600;
  text-decoration: none;
  color: var(--navy);
}

.guide-back::before { content: "\\2190"; margin-right: 7px; }

.guide-back:hover { background: var(--navy); border-color: var(--navy); color: #fff; }

.guide-bar-logo { width: 168px; }

.guide-hero {
  position: relative;
  background-image: url("dossani-paradise-bg.png");
  background-size: cover;
  background-position: center;
  color: #fff;
  border-bottom: 4px solid var(--red);
}

.guide-hero::after {
  content: "";
  position: absolute;
  inset: 0;
  background: linear-gradient(180deg, rgba(9, 13, 48, 0.42) 0%, rgba(9, 13, 48, 0.78) 100%);
}

.guide-hero-inner {
  position: relative;
  z-index: 1;
  max-width: 940px;
  margin: 0 auto;
  padding: 38px 24px 42px;
}

.guide-crumb {
  margin: 0 0 10px;
  font-size: 0.76rem;
  letter-spacing: 1.6px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.72);
}

.guide-title {
  margin: 0 0 12px;
  font-size: clamp(1.6rem, 3.6vw, 2.3rem);
  line-height: 1.2;
}

.guide-desc {
  margin: 0 0 16px;
  max-width: 720px;
  font-size: 0.98rem;
  color: rgba(255, 255, 255, 0.88);
}

.guide-tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }

.guide-tags .tag {
  background: rgba(255, 255, 255, 0.16);
  color: #fff;
}

.guide-actions {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
}

.guide-count {
  font-size: 0.8rem;
  letter-spacing: 1.1px;
  text-transform: uppercase;
  color: rgba(255, 255, 255, 0.82);
}

.guide-actions .btn-ghost { background: #fff; }

.guide-wrap {
  max-width: 940px;
  margin: 0 auto;
  padding: 40px 24px 64px;
}

.steps {
  list-style: none;
  margin: 0;
  padding: 0;
  counter-reset: step;
}

.step {
  padding: 20px;
  margin-bottom: 20px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  box-shadow: 0 1px 3px rgba(19, 26, 51, 0.06);
  scroll-margin-top: 76px;
}

.step-head { display: flex; align-items: flex-start; gap: 14px; }

.step-num {
  flex: 0 0 auto;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--navy);
  color: #fff;
  font-size: 0.88rem;
  font-weight: 700;
}

.step-text {
  padding-top: 4px;
  font-size: 1rem;
  color: var(--ink);
}

.step-text a { font-weight: 600; }

.step-shot {
  position: relative;
  margin: 16px 0 0;
  overflow: hidden;
  border-radius: 10px;
  background: #eef1f7;
  border: 1px solid var(--line);
}

.step-shot img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.overlay {
  position: absolute;
  transform: translate(-50%, -50%);
  border: 2px solid;
  pointer-events: none;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.55);
}

.overlay-circle { border-radius: 999px; }
.overlay-rect { border-radius: 4px; }

/* Section headings and callouts inside a guide */
.step-section { list-style: none; margin: 34px 0 18px; }

.step-section h2 {
  margin: 0;
  padding-bottom: 10px;
  font-size: 1.3rem;
  color: var(--navy-deep);
  border-bottom: 2px solid var(--red);
}

.note {
  display: flex;
  gap: 14px;
  align-items: flex-start;
  padding: 16px 18px;
  margin-bottom: 20px;
  border-radius: 12px;
  border: 1px solid;
  font-size: 0.95rem;
}

.note-label {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.7rem;
  font-weight: 700;
  letter-spacing: 1.1px;
  text-transform: uppercase;
  color: #fff;
}

.note-tip {
  background: #eef7f1;
  border-color: #bfe3cd;
  color: #14532d;
}

.note-tip .note-label { background: #16a34a; }

.note-warning {
  background: #fdf1f2;
  border-color: #f6c7cc;
  color: #7f1d24;
}

.note-warning .note-label { background: var(--red); }

.note-text a { color: inherit; text-decoration: underline; }

/* Pager */
.pager-row {
  display: flex;
  gap: 14px;
  margin-top: 30px;
}

.pager-slot { flex: 1; }

.pager {
  flex: 1;
  padding: 14px 18px;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 12px;
  text-decoration: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.pager:hover {
  border-color: rgba(27, 31, 107, 0.4);
  box-shadow: 0 8px 20px rgba(19, 26, 51, 0.1);
}

.pager-next { text-align: right; }

.pager-label {
  display: block;
  font-size: 0.72rem;
  letter-spacing: 1.3px;
  text-transform: uppercase;
  color: var(--muted);
}

.pager-name {
  display: block;
  margin-top: 3px;
  font-weight: 600;
  color: var(--navy-deep);
}

.to-top {
  position: fixed;
  right: 22px;
  bottom: 22px;
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--navy);
  color: #fff;
  font-size: 1.1rem;
  text-decoration: none;
  box-shadow: 0 8px 20px rgba(13, 18, 64, 0.35);
  opacity: 0.9;
}

.to-top:hover { background: var(--red); opacity: 1; }

/* Footer */
.footer {
  padding: 40px 24px 52px;
  text-align: center;
  background: var(--navy-deep);
  color: rgba(255, 255, 255, 0.78);
  font-size: 0.88rem;
}

.footer-logo {
  width: 220px;
  background: #fff;
  padding: 12px 18px;
  border-radius: 10px;
  margin-bottom: 16px;
}

@media (max-width: 640px) {
  .hero-inner { padding: 44px 20px 52px; }
  .search input { width: 100%; }
  .subnav-inner { padding: 10px 16px; }
  .wrap { padding: 0 16px 56px; }
}

/* Auth + editor */
.auth-body {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 24px;
  background: var(--navy-deep) url("dossani-paradise-bg.png") center / cover;
}

.auth-card {
  width: min(420px, 100%);
  padding: 28px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.28);
}

.auth-logo { width: 220px; display: block; margin: 0 auto 18px; }
.auth-card h1 { margin: 0 0 6px; font-size: 1.4rem; color: var(--navy-deep); text-align: center; }
.auth-sub { margin: 0 0 18px; color: var(--muted); text-align: center; font-size: 0.92rem; }
.auth-card label { display: block; margin-bottom: 12px; font-size: 0.86rem; font-weight: 600; color: var(--navy); }
.auth-card input {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font: inherit;
}
.auth-card .btn { width: 100%; text-align: center; margin-top: 8px; border: 0; cursor: pointer; }
.auth-error { color: var(--red); font-size: 0.88rem; margin: 0 0 8px; }
.auth-back { text-align: center; margin: 16px 0 0; font-size: 0.9rem; }
.auth-hint { margin: 12px 0 0; font-size: 0.85rem; color: var(--muted); text-align: center; }
.auth-static { font-size: 0.92rem; line-height: 1.55; color: var(--muted); }
.auth-static p { margin: 0 0 10px; }
.auth-static strong { color: var(--ink); }
.auth-steps { margin: 0 0 12px; padding-left: 20px; }
.auth-steps li { margin-bottom: 4px; }
.auth-static code {
  background: rgba(15, 23, 42, 0.06);
  border-radius: 4px;
  padding: 1px 5px;
  font-size: 0.88em;
}

.editor-body { background: var(--page); }
.editor-wrap { max-width: 940px; margin: 0 auto; padding: 28px 24px 72px; }
.editor-loading { text-align: center; padding: 80px 24px; color: var(--muted); }
.editor-header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 18px;
  flex-wrap: wrap;
}
.editor-header h1 { margin: 4px 0 0; color: var(--navy-deep); }
.editor-actions, .editor-bar-actions { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.editor-user { font-size: 0.86rem; color: var(--muted); }
.editor-status {
  margin: 0 0 16px;
  padding: 10px 14px;
  border-radius: 10px;
  font-size: 0.92rem;
}
.editor-status.is-ok { background: #eef7f1; color: #14532d; border: 1px solid #bfe3cd; }
.editor-status.is-error { background: #fdf1f2; color: #7f1d24; border: 1px solid #f6c7cc; }
.editor-panel {
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 18px;
  margin-bottom: 18px;
}
.editor-panel label { display: block; margin-bottom: 12px; font-size: 0.86rem; font-weight: 600; color: var(--navy); }
.editor-panel input, .editor-panel textarea, .block-text, .block-kind {
  display: block;
  width: 100%;
  margin-top: 6px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 10px;
  font: inherit;
  color: var(--ink);
  background: #fff;
}
.editor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.hint { font-weight: 500; color: var(--muted); }
.editor-panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  margin-bottom: 14px;
  flex-wrap: wrap;
}
.editor-panel-head h2 { margin: 0; font-size: 1.1rem; color: var(--navy-deep); }
.editor-add { display: flex; gap: 8px; flex-wrap: wrap; }
.editor-add button, .block-toolbar button {
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid var(--line);
  background: #fff;
  cursor: pointer;
  font: inherit;
  font-size: 0.84rem;
}
.editor-add button:hover, .block-toolbar button:hover { border-color: var(--navy); color: var(--navy); }
.block-card {
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 12px;
  margin-bottom: 12px;
  background: #fbfcff;
}
.block-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.block-badge {
  min-width: 42px;
  text-align: center;
  padding: 4px 8px;
  border-radius: 999px;
  background: var(--navy);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 700;
}
.block-kind { width: auto; min-width: 120px; margin: 0; }
.block-toolbar .danger { color: var(--red); border-color: rgba(226, 0, 26, 0.35); }
.block-image { margin-top: 10px; }
.block-image img {
  display: block;
  width: 100%;
  max-height: 280px;
  object-fit: contain;
  border-radius: 10px;
  border: 1px solid var(--line);
  background: #eef1f7;
}
.block-image.empty {
  padding: 18px;
  border: 1px dashed var(--line);
  border-radius: 10px;
  text-align: center;
}
.upload-btn {
  display: inline-block;
  margin-top: 8px;
  padding: 7px 12px;
  border-radius: 999px;
  border: 1px solid rgba(27, 31, 107, 0.35);
  color: var(--navy);
  font-size: 0.84rem;
  cursor: pointer;
  font-weight: 600;
}
@media (max-width: 720px) {
  .editor-grid { grid-template-columns: 1fr; }
}
"""

JS = """(function () {
  var search = document.getElementById('guide-search');
  var empty = document.getElementById('empty-state');
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  var groups = Array.prototype.slice.call(document.querySelectorAll('.group'));
  var sections = Array.prototype.slice.call(document.querySelectorAll('.section'));

  function apply(term) {
    if (!search) return;
    var q = term.trim().toLowerCase();
    var visible = 0;

    cards.forEach(function (card) {
      var hit =
        !q ||
        (card.dataset.name || '').indexOf(q) !== -1 ||
        (card.dataset.desc || '').indexOf(q) !== -1;
      card.hidden = !hit;
      if (hit) visible++;
    });

    groups.forEach(function (group) {
      var any = group.querySelector('.card:not([hidden])');
      group.hidden = !any;
    });

    sections.forEach(function (section) {
      var any = section.querySelector('.card:not([hidden])');
      section.hidden = !any;
    });

    if (empty) empty.hidden = visible !== 0;
  }

  if (search) {
    search.addEventListener('input', function () {
      apply(search.value);
    });
  }

  function rootPrefix() {
    return location.pathname.indexOf('/guides/') !== -1 ? '../' : '';
  }

  var SESSION_KEY = 'dpmEditorSession';
  var staticMode = false;

  function renderAuth(me) {
    var prefix = rootPrefix();
    document.querySelectorAll('[data-auth-slot]').forEach(function (slot) {
      slot.hidden = false;
      if (!me.authenticated) {
        slot.innerHTML = '<a class="nav-link" href="' + prefix + 'login.html">Editor sign in</a>';
        return;
      }
      var slug = slot.getAttribute('data-edit-slug');
      var bits = [];
      if (slug) {
        bits.push('<a class="btn btn-edit" href="' + prefix + 'edit.html?guide=' + encodeURIComponent(slug) + '">Edit guide</a>');
      }
      bits.push('<span class="editor-user">' + (me.user.email || 'Editor') + '</span>');
      bits.push('<button type="button" class="nav-link" data-logout>Sign out</button>');
      slot.innerHTML = bits.join('');
    });

    document.querySelectorAll('.auth-only').forEach(function (el) {
      el.hidden = !me.authenticated;
    });
  }

  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-logout]');
    if (!btn) return;
    e.preventDefault();
    if (staticMode) {
      try { sessionStorage.removeItem(SESSION_KEY); } catch (err) {}
      location.reload();
      return;
    }
    fetch('/api/logout', { method: 'POST' }).then(function () {
      location.reload();
    }).catch(function () {
      location.href = rootPrefix() + 'login.html';
    });
  });

  // On the published copy there is no API; editing is unlocked with an access code.
  function renderStaticAuth() {
    staticMode = true;
    document.body.setAttribute('data-static-site', 'true');
    var unlocked = false;
    try { unlocked = !!sessionStorage.getItem(SESSION_KEY); } catch (err) {}
    if (unlocked) {
      renderAuth({ authenticated: true, user: { email: 'Signed in with access code' } });
      return;
    }
    fetch(rootPrefix() + 'assets/editor-key.json', { cache: 'no-store' })
      .then(function (r) {
        if (r.ok) renderAuth({ authenticated: false });
      })
      .catch(function () {});
  }

  fetch('/api/me')
    .then(function (r) {
      var type = r.headers.get('content-type') || '';
      if (!r.ok || type.indexOf('application/json') === -1) throw new Error('no api');
      return r.json();
    })
    .then(renderAuth)
    .catch(renderStaticAuth);
})();
"""


def write_manifest(groups: list[dict]) -> None:
    flat = [
        {
            "slug": g["slug"],
            "name": g["name"],
            "url": g["url"],
            "description": g["description"],
            "section": g["section"],
            "subsection": g["subsection"],
            "tags": g["tags"],
            "pdf": g["pdf"],
        }
        for group in groups
        for g in group["guides"]
    ]
    (ROOT / "site-guides.json").write_text(json.dumps(flat, indent=1), encoding="utf-8")


def write_guide_pages(groups: list[dict]) -> tuple[int, list[str]]:
    """Render one page per guide that has scraped content. Returns (built, pending)."""
    GUIDE_DIR.mkdir(exist_ok=True)
    ordered = [g for group in groups for g in group["guides"] if g["url"]]
    contents = {}
    for guide in ordered:
        path = CONTENT_DIR / f'{guide["slug"]}.json'
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            steps = [b for b in data.get("blocks") or [] if b.get("kind") == "step"]
            if steps:
                contents[guide["slug"]] = data
                guide["page"] = f'guides/{guide["slug"]}.html'
                guide["steps"] = len(steps)

    ready = [g for g in ordered if g["slug"] in contents]
    # Guide-to-guide references in step text should stay on this site
    link_map = {scribe_key(g["url"]): f'{g["slug"]}.html' for g in ready}
    for g in ready:
        link_map[f'name:{slug(g["name"])}'] = f'{g["slug"]}.html'
        title = (contents[g["slug"]].get("title") or g["name"]).strip()
        link_map[f"name:{slug(title)}"] = f'{g["slug"]}.html'
    for i, guide in enumerate(ready):
        prev = ready[i - 1] if i else None
        nxt = ready[i + 1] if i + 1 < len(ready) else None
        page = guide_page_html(guide, contents[guide["slug"]], prev, nxt, link_map)
        (GUIDE_DIR / f'{guide["slug"]}.html').write_text(page, encoding="utf-8")

    pending = [g["name"] for g in ordered if g["slug"] not in contents]
    return len(ready), pending


def main():
    groups = build_groups()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    # Originals live outside the repo; in CI the committed copies are already in place.
    for src, dest in ((LOGO_SRC, "dpm-lockup.png"), (BG_SRC, "dossani-paradise-bg.png")):
        if src.exists():
            shutil.copyfile(src, assets / dest)
    (assets / "styles.css").write_text(CSS, encoding="utf-8")
    (assets / "site.js").write_text(JS, encoding="utf-8")

    write_manifest(groups)
    built, pending = write_guide_pages(groups)
    (ROOT / "index.html").write_text(build_html(groups), encoding="utf-8")

    total = 0
    for g in groups:
        label = f'{g["section"]} / {g["subsection"]}' if g["subsection"] else g["section"]
        total += len(g["guides"])
        print(f'{len(g["guides"]):3d}  {label}')
    print(f"TOTAL GUIDES={total}  GUIDE PAGES={built}")
    if pending:
        print(f"PENDING CONTENT ({len(pending)}): {pending}")


if __name__ == "__main__":
    main()
