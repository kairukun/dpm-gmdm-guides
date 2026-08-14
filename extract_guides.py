import json
import re
from pathlib import Path

TEMP = Path.home() / "AppData/Local/Temp"
html = (TEMP / "scribe-gmdm.html").read_text(encoding="utf-8", errors="replace")
raw = (TEMP / "scribe-next-data.json").read_text(encoding="utf-8-sig")
data = json.loads(raw)

hrefs = sorted(set(re.findall(r"https://scribehow\.com/(?:shared|viewer|embed)/[^\"'?<\s]+", html)))
json_urls = sorted(set(re.findall(r"https://scribehow\.com/(?:shared|viewer|embed)/[^\"'?<\s]+", raw)))

print("HREFS", len(hrefs))
print("JSON_URLS", len(json_urls))
print("UNION", len(set(hrefs) | set(json_urls)))

# Unique embedded scribes
uniq = {}

def walk(obj):
    if isinstance(obj, dict):
        if obj.get("type") == "scribe" and "name" in obj and "id" in obj:
            uniq[obj["id"]] = obj
        for v in obj.values():
            walk(v)
    elif isinstance(obj, list):
        for v in obj:
            walk(v)

walk(data)
print("UNIQUE_SCRIBES", len(uniq))
for name in sorted(h["name"] for h in uniq.values()):
    if any(x in name.lower() for x in ("pitco", "sos", "momos")):
        print("SPECIAL", name, uniq[[k for k, v in uniq.items() if v["name"] == name][0]]["id"])

res = data["props"]["pageProps"]["result"]
for key in ("scribe_documents", "embedded_documents", "editor_js_data"):
    val = res.get(key)
    print(f"--- {key} {type(val).__name__} ---")
    if isinstance(val, list):
        print("len", len(val))
        if val:
            print("item0_keys", list(val[0].keys()) if isinstance(val[0], dict) else type(val[0]))
            print("item0", json.dumps(val[0])[:800])
    elif isinstance(val, dict):
        print("keys", list(val.keys())[:30])
        blocks = val.get("blocks")
        if isinstance(blocks, list):
            types = {}
            for b in blocks:
                t = b.get("type") if isinstance(b, dict) else "?"
                types[t] = types.get(t, 0) + 1
            print("BLOCK_TYPES", types)
            for b in blocks:
                blob = json.dumps(b)
                if any(x in blob for x in ("Pitco", "SOS", "Momos", "scribeId", "documentId", "slug")):
                    print("BLOCK", b.get("type"), blob[:700])
                    print("---")
