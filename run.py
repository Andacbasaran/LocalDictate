"""Convenience entry point to launch LocalDictate directly."""

import sys
from pathlib import Path

# Ensure src/ is on sys.path when running `python run.py` without editable install
SRC_DIR = Path(__file__).resolve().parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from localdictate.main import main

if __name__ == "__main__":
    raise SystemExit(main())
