"""Give dashboard scripts/styles content URLs so WebView cannot reuse an old bundle."""
from hashlib import sha256
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def fingerprint(static: Path) -> None:
    # Local module URLs form a dependency chain (controller -> scene -> topology).
    # Refresh leaves before HTML, so a changed dependency also refreshes its importer.
    modules = sorted(static.glob("*.js"))
    pattern = re.compile(r'''(?P<lead>(?:from\s*|import\(\s*)['"])(?P<prefix>\./|/static/)(?P<name>[a-zA-Z0-9_-]+\.js)(?:\?v=[a-zA-Z0-9_-]+)?(?P<quote>['"])''')

    def module_reference(match):
        target = static / match["name"]
        if not target.is_file():
            raise ValueError("Missing local module: " + match["name"])
        digest = sha256(target.read_bytes()).hexdigest()[:16]
        return f'{match["lead"]}{match["prefix"]}{match["name"]}?v={digest}{match["quote"]}'

    for _ in range(len(modules) + 1):
        changed = False
        for module in modules:
            original = module.read_text(encoding="utf-8")
            updated = pattern.sub(module_reference, original)
            if updated != original:
                module.write_text(updated, encoding="utf-8", newline="\n")
                changed = True
        if not changed:
            break
    else:
        raise ValueError("Local module references contain a fingerprint cycle")

    def replace(match):
        name = match["name"]
        digest = sha256((static / name).read_bytes()).hexdigest()[:16]
        return f'/static/{name}?v={digest}'

    for page in static.glob("*.html"):
        source = page.read_text(encoding="utf-8")
        updated = pattern.sub(module_reference, source)
        updated = re.sub(r'/static/(?P<name>[a-zA-Z0-9_-]+\.(?:js|css))(?:\?v=[a-zA-Z0-9_-]+)?', replace, updated)
        if updated != source:
            page.write_text(updated, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    fingerprint(ROOT / "clipbot" / "dashboard" / "static")
