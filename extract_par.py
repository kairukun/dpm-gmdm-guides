import json
import re
from pathlib import Path

html = Path.home().joinpath("AppData/Local/Temp/scribe-par-full.html").read_text(encoding="utf-8", errors="replace")
print("html_len", len(html))
m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html)
print("has_next", bool(m))
if not m:
    # dump some unique strings
    urls = re.findall(r"https://scribehow\.com/[^\s\"'<>]+", html)
    print("urls", len(urls))
    for u in sorted(set(urls))[:50]:
        print(u)
    raise SystemExit

raw = m.group(1)
data = json.loads(raw)
Path.home().joinpath("AppData/Local/Temp/scribe-par-next.json").write_text(raw, encoding="utf-8")
res = data.get("props", {}).get("pageProps", {}).get("result") or {}
print("result_keys", list(res.keys())[:40] if isinstance(res, dict) else type(res))
print("name", res.get("name") if isinstance(res, dict) else None)
print("error", data.get("props", {}).get("pageProps", {}).get("error"))
content = (res.get("editor_js_data") or {}).get("content") if isinstance(res, dict) else None
print("blocks", len(content) if isinstance(content, list) else content)
guides = []
if isinstance(content, list):
    for i, b in enumerate(content):
        t = b.get("type")
        attrs = b.get("attrs") or {}
        if t == "IncludeScribeExtension":
            scribe = attrs.get("scribe") or {}
            url = attrs.get("scribeUrl") or scribe.get("documentUrl")
            name = scribe.get("name") or attrs.get("placeholderText")
            print(f"[{i}] SCRIBE {name} | {url}")
            guides.append({"name": name, "url": url})
        elif t == "heading":
            texts = []
            def walk(n):
                if isinstance(n, dict):
                    if n.get("text"): texts.append(n["text"])
                    for v in n.values(): walk(v)
                elif isinstance(n, list):
                    for v in n: walk(v)
            walk(b)
            print(f"[{i}] HEADING {' '.join(texts)}")
        elif t == "paragraph":
            blob = json.dumps(b)
            hrefs = re.findall(r"https://scribehow\.com/[^\s\"']+", blob)
            print(f"[{i}] PARA hrefs={hrefs} {blob[:200]}")
        else:
            print(f"[{i}] {t}")

print("GUIDE_COUNT", len(guides))
