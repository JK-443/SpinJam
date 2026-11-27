"""Run the Tizen display logic suite (no browser, no Home Assistant)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGIC_TEST = ROOT / "tests" / "test_tizen_logic.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_tizen_logic_node_suite() -> None:
    result = subprocess.run(
        ["node", "--test", str(LOGIC_TEST)],
        cwd=str(ROOT),
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + "\n" + result.stderr
