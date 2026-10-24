"""Check a native web export before it enters an app bundle."""

import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit


class NativeHTML(HTMLParser):
    """Executable startup must not cross from an HTTPS origin to a custom scheme."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.scripts: list[str] = []
        self.in_script = False

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        attrs = dict(attributes)
        if tag == "script":
            if attrs.get("src"):
                raise ValueError("Native bootstrap must not fetch executable scripts")
            self.in_script = True
            self.scripts.append("")
        if tag == "link" and attrs.get("rel") in {"modulepreload", "stylesheet"}:
            raise ValueError("Native executable and stylesheet must be inline for HTTPS profiles")

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.scripts[-1] += data


def verify(root: Path) -> dict[str, str]:
    root = root.resolve()
    html = (root / "index.html").read_text()
    parsed = NativeHTML()
    parsed.feed(html)
    if not any(
        re.search(r"__sveltekit_[a-z0-9]+\.app\.start\(", script) for script in parsed.scripts
    ):
        raise ValueError("Wrong export: expected SvelteKit's inline native bootstrap")
    if any(
        re.search(r"""import\s*\(\s*["'](?:/_app/|cognisbundle:)""", script)
        for script in parsed.scripts
    ):
        raise ValueError("Native bootstrap still fetches an executable module")
    required: set[str] = set()
    for file in [root / "index.html", *root.rglob("*.js"), *root.rglob("*.css")]:
        content = file.read_text()
        for reference in re.findall(
            r"""(?:from\s*|import\s*(?:\(\s*)?|(?:src|href)=)["']([^"']+)["']""", content
        ):
            url = urlsplit(reference)
            if url.scheme == "cognisbundle":
                if url.netloc != "app":
                    raise ValueError("Unexpected bundle authority")
                target = root / unquote(url.path.lstrip("/"))
            elif not url.scheme and reference.startswith(("./", "../")) and file.suffix == ".js":
                target = file.parent / unquote(url.path)
            else:
                continue
            # Navigation links and optional documentation media are not executable
            # module dependencies and must not be mistaken for startup assets.
            if target.suffix not in {".js", ".css"}:
                continue
            target = target.resolve()
            if not target.is_relative_to(root) or not target.is_file():
                raise ValueError(f"Missing or escaped bundle asset: {target.name}")
            required.add(target.relative_to(root).as_posix())
    for name in required:
        if not (root / name).is_file():
            raise ValueError(f"Missing bundle asset: {name}")
    return {
        file.relative_to(root).as_posix(): hashlib.sha256(file.read_bytes()).hexdigest()
        for file in sorted(root.rglob("*"))
        if file.is_file()
    }


if __name__ == "__main__":
    manifest = verify(Path(sys.argv[1]))
    Path(sys.argv[2]).write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n")
    print(f"Verified native export: {len(manifest)} files")
