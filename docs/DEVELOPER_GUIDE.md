# Developer Documentation

## Frozen Specification Authority

Architecture and behavioral rules are defined only in:

- docs/ARCHITECTURE.md

Implementation work must preserve the frozen layered architecture and terminology from that document.

## Release Validation
- Compile: `py -m poetry run python -m compileall engine run.py`
- Startup: `py -m poetry run python run.py`
- Tests: `py -m poetry run pytest`
