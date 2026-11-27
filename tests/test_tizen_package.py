"""The Tizen widget is packaged outside the HACS integration folder."""

from __future__ import annotations

from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
TIZEN = ROOT / "tizen"
WGT = TIZEN / "SpinJam.wgt"
PACKED = (
    "config.xml",
    "index.html",
    "icon.png",
    "css/app.css",
    "js/logic.js",
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
    logic = (TIZEN / "js" / "logic.js").read_text(encoding="utf-8")
    page = (TIZEN / "index.html").read_text(encoding="utf-8")
    style = (TIZEN / "css" / "app.css").read_text(encoding="utf-8")
    bundled = "\n".join((script, logic, page, style))

    assert "localStorage" in script
    assert "tizen.power" in script
    assert "setScreenSaver" in script
    assert "10009" in script
    assert "scheduleReconnect" in script
    assert "/api/websocket" in logic
    assert "list_for_display" in script
    assert "subscribe_entities" in script
    assert "lyric_lines" in logic
    assert "artwork_hd" in script
    assert "entity_picture" in logic
    assert "media_position" in logic
    assert "Waiting for music" in page
    assert 'id="ha-base-url"' in page
    assert 'id="ha-token"' in page
    assert "<iframe" not in page.lower()
    assert "iframe" not in script

    assert "media_player." not in bundled
    assert "switch." not in bundled
    assert "number." not in bundled
    assert "sensor." not in bundled
    assert "homeassistant.local" not in bundled
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", bundled)

    manifest = (TIZEN / "config.xml").read_text(encoding="utf-8")
    assert 'package="SpinJamDsp"' in manifest
    assert 'id="SpinJamDsp.Display"' in manifest
    assert "http://tizen.org/privilege/internet" in manifest
    assert "http://tizen.org/privilege/tv.inputdevice" in manifest
    assert "http://developer.samsung.com/privilege/productinfo" in manifest
    assert "http://tizen.org/privilege/power" in manifest
    assert "allow-navigation" in manifest
    assert 'version="0.8.1"' in manifest

    readme = (TIZEN / "README.md").read_text(encoding="utf-8")
    assert "long-lived" in readme.lower()
    assert "no longer required" in readme.lower()
    assert "localStorage" in readme
