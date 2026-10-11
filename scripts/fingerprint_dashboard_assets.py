"""Give dashboard scripts/styles content URLs so WebView cannot reuse an old bundle."""
from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(static: Path) -> None:
    page = static / "index.html"
    source = page.read_text(encoding="utf-8")

    def replace(match):
        name = match["name"]
        digest = sha256((static / name).read_bytes()).hexdigest()[:16]
        return f'/static/{name}?v={digest}'

    updated = re.sub(r'/static/(?P<name>[a-zA-Z0-9_-]+\.(?:js|css))(?:\?v=[a-zA-Z0-9_-]+)?', replace, source)
    if updated != source:
        page.write_text(updated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    fingerprint(ROOT / "clipbot" / "dashboard" / "static")
