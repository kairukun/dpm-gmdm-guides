"""Report nearly-blank PDF pages and optionally strip them."""
import sys
from pathlib import Path

import fitz

ROOT = Path(r"C:\Users\James\Documents\Ampler-GMDM-Guide-PDFs")


def page_ink_ratio(page, zoom=0.35):
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY, alpha=False)
    samples = pix.samples
    if not samples:
        return 0.0
    # count pixels darker than near-white
    dark = sum(1 for b in samples if b < 250)
    return dark / len(samples)


def is_empty(page, threshold=0.004):
    text = (page.get_text() or "").strip()
    if len(text) >= 15:
        return False
    return page_ink_ratio(page) < threshold


def analyze(path: Path, threshold=0.004):
    doc = fitz.open(path)
    empty = []
    for i, page in enumerate(doc):
        if is_empty(page, threshold):
            empty.append((i + 1, page_ink_ratio(page)))
    count = doc.page_count
    doc.close()
    return count, empty


def strip_empty(path: Path, dest: Path | None = None, threshold=0.004):
    doc = fitz.open(path)
    keep = [i for i, page in enumerate(doc) if not is_empty(page, threshold)]
    if not keep:
        keep = [0]
    if len(keep) == doc.page_count:
        doc.close()
        return 0
    out = fitz.open()
    for i in keep:
        out.insert_pdf(doc, from_page=i, to_page=i)
    dest = dest or path
    removed = doc.page_count - len(keep)
    tmp = dest.with_suffix(".tmp.pdf")
    out.save(tmp, deflate=True, garbage=4)
    out.close()
    doc.close()
    tmp.replace(dest)
    return removed


def main():
    args = sys.argv[1:]
    do_strip = "--strip" in args
    args = [a for a in args if a != "--strip"]
    folder = ROOT / "pdfs"
    if args and all(Path(a).suffix.lower() == ".pdf" or a.endswith(".pdf") for a in args):
        files = [folder / a if not Path(a).is_absolute() else Path(a) for a in args]
        files = [p for p in files if p.exists()]
    else:
        files = sorted(folder.glob("*.pdf"))
        if args:
            files = [p for p in files if any(a.lower() in p.name.lower() for a in args)]
    total_empty = 0
    for p in files:
        pages, empty = analyze(p)
        total_empty += len(empty)
        mark = f" empty={ [e[0] for e in empty] }" if empty else ""
        print(f"{pages:3d}p {p.name}{mark}")
        if do_strip and empty:
            n = strip_empty(p)
            print(f"    stripped {n}")
    print(f"FILES={len(files)} EMPTY_PAGES={total_empty}")


if __name__ == "__main__":
    main()
