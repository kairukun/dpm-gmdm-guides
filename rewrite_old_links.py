"""Rewrite old ScribeHow / Ampler links in guide-content to local DPM pages."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONTENT = ROOT / "guide-content"
MANIFEST = ROOT / "site-guides.json"
CONTACT = "kyle@dossaniparadise.com"

SCRIBE_URL = re.compile(
    r"https?://(?:www\.)?scribehow\.com/(?:shared|viewer)/([^/?\s)\"'#]+)",
    re.I,
)
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
ANGLE_URL = re.compile(r"<(https?://[^>]+)>")
BARE_SCRIBE = re.compile(
    r"(?<!\()https?://(?:www\.)?scribehow\.com/(?:shared|viewer)/[^\s)\"'<>]+",
    re.I,
)
AMPLER_MAIL = re.compile(r"(?:mailto:)?[A-Za-z0-9._%+-]+@amplergroup\.com", re.I)


def normalize_key(url: str) -> str:
    url = (url or "").split("?")[0].rstrip("/")
    return url.rsplit("/", 1)[-1].lower()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def build_maps() -> tuple[dict[str, str], dict[str, str]]:
    by_key: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for g in json.loads(MANIFEST.read_text(encoding="utf-8")):
        if not g.get("url") or not g.get("slug"):
            continue
        by_key[normalize_key(g["url"])] = g["slug"]
        for label in (g.get("name"), g.get("slug")):
            if label:
                by_name[slugify(label)] = g["slug"]
    # Also index scraped titles
    for path in CONTENT.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        slug = data.get("slug") or path.stem
        for label in (data.get("title"), data.get("name"), slug):
            if label:
                by_name[slugify(label)] = slug
        if data.get("sourceUrl"):
            by_key[normalize_key(data["sourceUrl"])] = slug
    return by_key, by_name


def local_for(url: str, label: str, by_key: dict[str, str], by_name: dict[str, str]) -> str | None:
    key = normalize_key(url)
    if key in by_key:
        # Prefer label when the URL itself is wrong (seen in source data).
        label_slug = by_name.get(slugify(label))
        if label_slug and label_slug != by_key[key]:
            # If the label clearly names another guide, trust the label.
            return label_slug
        return by_key[key]
    return by_name.get(slugify(label))


def rewrite_text(text: str, by_key: dict[str, str], by_name: dict[str, str]) -> str:
    original = text

    def md_sub(m: re.Match) -> str:
        label, target = m.group(1), m.group(2).strip()
        if AMPLER_MAIL.fullmatch(target.replace("mailto:", "")) or "amplergroup.com" in target.lower():
            return f"[{CONTACT}](mailto:{CONTACT})"
        if "scribehow.com" in target.lower():
            slug = local_for(target, label, by_key, by_name)
            if slug:
                return f"[{label}]({slug}.html)"
            return label  # drop dead old-guide link
        return m.group(0)

    text = MD_LINK.sub(md_sub, text)
    text = ANGLE_URL.sub(
        lambda m: (
            f"<{CONTACT}>"
            if "amplergroup.com" in m.group(1).lower()
            else (
                f"{local_for(m.group(1), '', by_key, by_name)}.html"
                if "scribehow.com" in m.group(1).lower()
                and local_for(m.group(1), "", by_key, by_name)
                else m.group(0)
            )
        ),
        text,
    )
    text = BARE_SCRIBE.sub(
        lambda m: (
            f"{local_for(m.group(0), '', by_key, by_name)}.html"
            if local_for(m.group(0), "", by_key, by_name)
            else m.group(0)
        ),
        text,
    )
    text = AMPLER_MAIL.sub(CONTACT, text)

    # Spacing around rewritten links: "](x.html)to" -> "](x.html) to"
    text = re.sub(r"(\]\([^)]+\))([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"([A-Za-z:])(\[[^\]]+\]\([^)]+\))", r"\1 \2", text)
    text = re.sub(r" {2,}", " ", text)
    return text if text != original else original


def main() -> None:
    by_key, by_name = build_maps()
    changed_files = 0
    changed_blocks = 0
    for path in sorted(CONTENT.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        dirty = False
        for block in data.get("blocks") or []:
            text = block.get("text") or ""
            new = rewrite_text(text, by_key, by_name)
            if new != text:
                block["text"] = new
                dirty = True
                changed_blocks += 1
                print(f"{path.name}: {text[:90]!r}")
                print(f"  -> {new[:90]!r}")
        # Drop provenance URLs from published content payloads so editors don't re-share them
        if data.pop("sourceUrl", None) is not None:
            dirty = True
        if dirty:
            data["linksRewrittenAt"] = (
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            )
            path.write_text(json.dumps(data, indent=1), encoding="utf-8")
            changed_files += 1
    print(f"Updated {changed_blocks} blocks in {changed_files} files")


if __name__ == "__main__":
    main()
