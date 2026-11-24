"""Convenience entry point to launch LocalDictate directly (`python run.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent / "src"
if SRC_DIR.is_dir() and str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from localdictate.main import main

if __name__ == "__main__":
    raise SystemExit(main())
