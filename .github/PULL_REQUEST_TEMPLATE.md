## Summary

Describe the changes in this pull request and why they improve LocalDictate.

## Type of Change

- [ ] Bug fix (non-breaking change fixing an issue)
- [ ] New feature (non-breaking change adding functionality)
- [ ] Performance or cross-platform improvement
- [ ] Packaging, CI/CD, or documentation update

## Verification Checklist

- [ ] `ruff check .` passes with 0 errors
- [ ] `QT_QPA_PLATFORM=offscreen PYTHONPATH=src python -m unittest discover -s tests -v` passes 100%
- [ ] Cross-platform impact checked (Windows / macOS / Linux)
- [ ] Privacy guarantee preserved (no telemetry or unexpected outbound calls)
