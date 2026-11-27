"""The Tizen widget is packaged outside the HACS integration folder."""

from __future__ import annotations

from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TIZEN = ROOT / "tizen"
WGT = TIZEN / "SpinJam.wgt"
PACKED = (
    "config.xml",
    "index.html",
    "icon.png",
    "css/app.css",
    "js/app.js",
)


def test_wgt_matches_source_and_stays_out_of_the_integration() -> None:
    assert WGT.is_file()
    assert "custom_components" not in WGT.parts
    with zipfile.ZipFile(WGT) as archive:
        names = set(archive.namelist())
        for name in PACKED:
            assert archive.read(name) == (TIZEN / name).read_bytes()
    assert names == set(PACKED)

    script = (TIZEN / "js" / "app.js").read_text(encoding="utf-8")
    assert "localStorage" in script
    assert "tizen.power" in script
    assert "setScreenSaver" in script
    assert "10009" in script
    assert "scheduleReload" in script
    page = (TIZEN / "index.html").read_text(encoding="utf-8")
    assert 'id="dashboard-url"' in page
    assert 'id="dashboard"' in page
    manifest = (TIZEN / "config.xml").read_text(encoding="utf-8")
    assert "http://tizen.org/privilege/internet" in manifest
    assert "allow-navigation" in manifest
    readme = (TIZEN / "README.md").read_text(encoding="utf-8")
    assert "trusted_networks" in readme
    assert "long-lived" in readme.lower()
