"""Run the Node card-layout suite (same harness as the playback clock)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_TEST = ROOT / "tests" / "test_card_layout.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_card_layout_node_suite() -> None:
    result = subprocess.run(
        ["node", "--test", str(LAYOUT_TEST)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
