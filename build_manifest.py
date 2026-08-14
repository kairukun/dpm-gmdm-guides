"""Build a unique guide manifest from the GM/DM ScribeHow page."""
import json
import re
from pathlib import Path
from urllib.parse import unquote

TEMP = Path.home() / "AppData/Local/Temp"
OUT = Path(r"C:\Users\James\Documents\Ampler-GMDM-Guide-PDFs")
raw = (TEMP / "scribe-next-data.json").read_text(encoding="utf-8-sig")
html = (TEMP / "scribe-gmdm.html").read_text(encoding="utf-8", errors="replace")
data = json.loads(raw)

guides = {}  # url -> {name, url, source}


def slug_from_url(url: str) -> str:
    return unquote(url.rstrip("/").split("/")[-1])


def add(url: str, name: str, source: str):
    if not url:
        return
    url = url.split("?")[0].rstrip("/")
    existing = guides.get(url)
    if existing:
        if name and (not existing["name"] or len(name) > len(existing["name"])):
            existing["name"] = name
        return
    guides[url] = {"name": name or slug_from_url(url), "url": url, "source": source}


blocks = data["props"]["pageProps"]["result"]["editor_js_data"]["content"]
for b in blocks:
    if not isinstance(b, dict):
        continue
    attrs = b.get("attrs") or {}
    if b.get("type") == "IncludeScribeExtension":
        scribe = attrs.get("scribe") or {}
        add(attrs.get("scribeUrl") or scribe.get("documentUrl"), scribe.get("name") or attrs.get("placeholderText"), "gmdm-embed")
    elif b.get("type") == "IncludePageExtension":
        doc = attrs.get("document") or {}
        add(attrs.get("pageUrl") or doc.get("documentUrl"), doc.get("name") or "Included page", "gmdm-page")

for url in re.findall(r"https://scribehow\.com/(?:shared|viewer|embed)/[^\"'?<\s]+", html):
    add(url, "", "gmdm-href")

# Prefer shared over viewer when both exist for same slug id
by_id = {}
for url, g in list(guides.items()):
    tail = url.split("__")[-1] if "__" in url else url
    by_id.setdefault(tail, []).append(url)

for tail, urls in by_id.items():
    shared = [u for u in urls if "/shared/" in u]
    viewer = [u for u in urls if "/viewer/" in u]
    if shared and viewer:
        for u in viewer:
            guides.pop(u, None)


def safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120] or "untitled"


items = sorted(guides.values(), key=lambda g: g["name"].lower())
used = set()
for g in items:
    base = safe_filename(g["name"])
    fname = base
    n = 2
    while fname.lower() in used:
        fname = f"{base} ({n})"
        n += 1
    used.add(fname.lower())
    g["filename"] = fname + ".pdf"

(OUT / "guides.json").write_text(json.dumps(items, indent=2), encoding="utf-8")
print(f"Wrote {len(items)} guides")
for g in items:
    print(f"- {g['filename']}")
    print(f"  {g['url']}")
