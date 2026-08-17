"""Compatibility entry point for the canonical HA Docs anchor checker."""

import pathlib
import runpy
import sys


RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "ha_docs" / "check_anchors.py"
sys.path.insert(0, str(RUNTIME.parent))
runpy.run_path(str(RUNTIME), run_name="__main__")
