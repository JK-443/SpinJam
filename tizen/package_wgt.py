#!/usr/bin/env python3
"""Build the unsigned SpinJam Tizen widget.

The result is ``tizen/SpinJam.wgt``. A TV will not install it until you sign
it with your own certificate. See README.md.
"""

from __future__ import annotations

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
FILES = (
    "config.xml",
    "index.html",
    "icon.png",
    "css/app.css",
    "js/app.js",
)
OUTPUT = ROOT / "SpinJam.wgt"


def main() -> None:
    missing = [name for name in FILES if not (ROOT / name).is_file()]
    if missing:
        raise SystemExit("missing widget files: " + ", ".join(missing))
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT / name, name)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
