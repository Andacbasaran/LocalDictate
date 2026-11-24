# Contributing to LocalDictate

Thank you for your interest in contributing to **LocalDictate**! Bug fixes, cross-platform improvements, new snippet starter packs, translations, and compatibility reports are all warmly welcome.

## Development Setup

```bash
git clone https://github.com/Andacbasaran/LocalDictate.git
cd LocalDictate

python3.11 -m venv .venv
# macOS / Linux:
source .venv/bin/activate
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
pip install ruff pytest
```

Run Studio from source:

```bash
python main.py
```

## Code Style & Quality Gates

Before opening a pull request, make sure all local checks pass cleanly:

```bash
# 1. Lint check (zero errors required)
ruff check .

# 2. Full automated unit & offscreen UI smoke tests
QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m unittest discover -s tests -v

# 3. Optional: run local pipeline benchmark
QT_QPA_PLATFORM=offscreen python scripts/benchmark.py --no-visuals
```

## Architecture Guidelines

- **100% Offline-First Privacy**: Never add telemetry, analytics, or silent outbound network requests. Any optional network feature (GitHub update check, external BYOK LLM) must respect `config.offline_only`.
- **Cross-Platform Guardrails**:
  - Guard all `ctypes.windll` calls to `sys.platform == "win32"` with explicit 64-bit `argtypes`/`restype`.
  - Guard Cocoa / Quartz / Carbon logic to `sys.platform == "darwin"`.
  - Never emit Qt signals directly from PortAudio's C callback thread.
  - Never overwrite or restore clipboard contents if paste execution failed.
- **UI Consistency**: Follow the Studio 2.0 palette (`#0A0A0C` canvas, `#111113` sidebar, `#141417` cards, `#24242A` 1px borders, Electric Violet `#8B5CF6`, Emerald `#10B981`, Rose `#E11D48`) and use vector icons from `src/localdictate/ui/widgets.py`.

## Pull Request Process

1. Fork the repository and create a feature branch (`feat/...` or `fix/...`).
2. Add or update unit tests in `tests/` covering your change.
3. Ensure CI (Ruff + Windows/macOS/Linux test matrix) passes.
4. Open a pull request using the repository PR template.
