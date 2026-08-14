"""Organize PDFs into ScribeHow website category folders."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

ROOT = Path(r"C:\Users\James\Documents\Ampler-GMDM-Guide-PDFs")
PDF_ROOT = ROOT / "pdfs"
MANIFEST = ROOT / "guides.json"
TEMP = Path.home() / "AppData/Local/Temp"


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


def safe_folder(name: str) -> str:
    name = name.replace("/", "-")
    name = re.sub(r'[<>:"\\|?*]', "-", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    # Shorten long XBO heading
    if name.lower().startswith("xbo-rti"):
        return "XBO-RTI"
    return name


def load_categories():
    raw = (TEMP / "scribe-next-data.json").read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    blocks = data["props"]["pageProps"]["result"]["editor_js_data"]["content"]
    section = None
    subsection = None
    by_url = {}
    by_name = {}
    for b in blocks:
        t = b.get("type")
        attrs = b.get("attrs") or {}
        if t == "heading":
            level = attrs.get("level") or 2
            title = " ".join(texts(b)).strip()
            if level <= 2:
                section = title
                subsection = None
            else:
                subsection = title
            continue
        if t == "IncludeScribeExtension":
            scribe = attrs.get("scribe") or {}
            name = scribe.get("name") or attrs.get("placeholderText")
            url = attrs.get("scribeUrl") or scribe.get("documentUrl")
        elif t == "IncludePageExtension":
            doc = attrs.get("document") or {}
            name = doc.get("name")
            url = attrs.get("pageUrl") or doc.get("documentUrl")
        else:
            continue
        if not url:
            continue
        url = url.split("?")[0].rstrip("/")
        # Prefer shared over viewer later; store both forms
        folder_parts = [safe_folder(section)]
        if subsection:
            folder_parts.append(safe_folder(subsection))
        cat = {
            "folder": str(Path(*folder_parts)),
            "section": section,
            "subsection": subsection,
            "name": name,
        }
        by_url[url] = cat
        by_url[url.replace("/viewer/", "/shared/")] = cat
        by_url[url.replace("/shared/", "/viewer/")] = cat
        if name:
            by_name[name.strip().lower()] = cat
    return by_url, by_name


# PAR POS nested page guides (from earlier extract)
PAR_POS = {
    "Adjust KDS Routing.pdf",
    "Assigning Drawers.pdf",
    "Clocking InOut.pdf",
    "Gift Cards.pdf",
    "Issuing Refund.pdf",
    "Kiosk Orders.pdf",
    "ManagerEmployee Discounts and Guest Recovery.pdf",
    "Zoho Workflow.pdf",
    "Remove PIN Access Card Only DMs Only.pdf",
    "Rerouting Printers.pdf",
    "Ringing inEditingTendering Order.pdf",
    "Setting Login Clock In Number.pdf",
    "PAR POS Guides.pdf",
}


def main():
    by_url, by_name = load_categories()
    guides = json.loads(MANIFEST.read_text(encoding="utf-8"))

    # Flatten any existing nested PDFs back to pdfs root temporarily except we move from root only
    existing = list(PDF_ROOT.rglob("*.pdf"))
    # Prefer root-level files; ignore copies inside old PAR POS Guides folder if root has same name
    root_files = {p.name: p for p in PDF_ROOT.glob("*.pdf")}

    moves = []
    unmatched = []

    for g in guides:
        src = root_files.get(g["filename"])
        if not src or not src.exists():
            # try find anywhere
            candidates = [p for p in existing if p.name == g["filename"]]
            src = candidates[0] if candidates else None
        if not src:
            unmatched.append((g["filename"], "missing file"))
            continue

        url = g["url"].split("?")[0].rstrip("/")
        cat = by_url.get(url) or by_url.get(url.replace("/viewer/", "/shared/"))
        if not cat:
            cat = by_name.get(g["name"].strip().lower())

        if g["filename"] in PAR_POS:
            dest_dir = PDF_ROOT / "PAR POS Guides"
        elif cat:
            dest_dir = PDF_ROOT / cat["folder"]
        else:
            dest_dir = PDF_ROOT / "Uncategorized"
            unmatched.append((g["filename"], "no category"))

        dest = dest_dir / g["filename"]
        moves.append((src, dest, dest_dir))

    # Execute moves
    for src, dest, dest_dir in moves:
        dest_dir.mkdir(parents=True, exist_ok=True)
        if src.resolve() == dest.resolve():
            continue
        if dest.exists():
            dest.unlink()
        shutil.move(str(src), str(dest))
        print(f"MOVE {src.name} -> {dest.relative_to(PDF_ROOT)}")

    # Remove empty leftover dirs / old duplicate renamed PAR copies
    for p in sorted(PDF_ROOT.rglob("*"), reverse=True):
        if p.is_dir():
            try:
                next(p.iterdir())
            except StopIteration:
                p.rmdir()
                print(f"RMDIR {p.relative_to(PDF_ROOT)}")

    # Summary tree
    print("\n=== FOLDER TREE ===")
    for folder in sorted({d for d in PDF_ROOT.rglob("*") if d.is_dir()}):
        files = sorted(folder.glob("*.pdf"))
        if not files:
            continue
        print(f"\n{folder.relative_to(PDF_ROOT)}/ ({len(files)})")
        for f in files:
            print(f"  - {f.name}")

    leftover = sorted(PDF_ROOT.glob("*.pdf"))
    if leftover:
        print("\nLEFTOVER ROOT:")
        for f in leftover:
            print(f"  - {f.name}")

    if unmatched:
        print("\nUNMATCHED:")
        for name, why in unmatched:
            print(f"  - {name}: {why}")


if __name__ == "__main__":
    main()
