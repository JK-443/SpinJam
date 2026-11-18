"""Run the Node playback-clock suite (card clock has no browser harness)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLOCK_TEST = ROOT / "tests" / "test_playback_clock.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_playback_clock_node_suite() -> None:
    result = subprocess.run(
        ["node", "--test", str(CLOCK_TEST)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
