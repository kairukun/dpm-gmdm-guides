import re
from pathlib import Path

html = Path.home().joinpath("AppData/Local/Temp/scribe-one.html").read_text(encoding="utf-8", errors="replace")

for tid in [
    "viewer-navigation-bar",
    "document-header",
    "action-section",
    "action-image-wrapper",
    "glow-image",
    "action-instruction",
]:
    i = html.find(f'data-testid="{tid}"')
    print(f"\n===== {tid} idx={i} =====")
    if i >= 0:
        print(html[max(0, i - 120) : i + 400])
