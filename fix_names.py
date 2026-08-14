import json
import re
from pathlib import Path

OUT = Path(r"C:\Users\James\Documents\Ampler-GMDM-Guide-PDFs")
guides = json.loads((OUT / "guides.json").read_text(encoding="utf-8"))

def humanize(url: str) -> str:
    slug = url.rstrip("/").split("/")[-1]
    name = slug.split("__")[0]
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name or slug

for g in guides:
    # Replace slug-looking filenames with humanized titles
    stem = Path(g["filename"]).stem
    if "__" in stem or stem == g["url"].rstrip("/").split("/")[-1]:
        g["name"] = humanize(g["url"])

used = set()
for g in guides:
    base = re.sub(r'[<>:"/\\|?*]', "-", g["name"])
    base = re.sub(r"\s+", " ", base).strip(" .")[:120]
    fname = base
    n = 2
    while fname.lower() in used:
        fname = f"{base} ({n})"
        n += 1
    used.add(fname.lower())
    g["filename"] = fname + ".pdf"

guides.sort(key=lambda x: x["name"].lower())
(OUT / "guides.json").write_text(json.dumps(guides, indent=2), encoding="utf-8")
print(len(guides))
for g in guides:
    print(g["filename"])
