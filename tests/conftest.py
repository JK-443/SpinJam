"""Shared pytest path setup for custom_components imports."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_HAS_HA_PLUGIN = False
try:
    import pytest_homeassistant_custom_component  # noqa: F401

    _HAS_HA_PLUGIN = True
    pytest_plugins = ["pytest_homeassistant_custom_component"]
except ImportError:
    pytest_plugins = []


if _HAS_HA_PLUGIN:

    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations(enable_custom_integrations):  # noqa: ANN001
        yield
