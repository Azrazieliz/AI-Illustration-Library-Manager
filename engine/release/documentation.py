from __future__ import annotations

from pathlib import Path

from engine.release.metadata import ReleaseMetadata


def generate_release_documents(*, root: Path, metadata: ReleaseMetadata) -> list[Path]:
    docs_dir = root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    api_path = docs_dir / "API.md"
    user_path = docs_dir / "USER_GUIDE.md"
    dev_path = docs_dir / "DEVELOPER_GUIDE.md"
    architecture_path = docs_dir / "ARCHITECTURE.md"
    changelog_path = root / "CHANGELOG.md"

    api_path.write_text(
        "# API Documentation\n\n"
        f"Generated for {metadata.app_name} {metadata.version}.\n\n"
        "## Stable Entrypoints\n"
        "- run.main\n"
        "- engine.config.settings\n"
        "- engine.logging.configure\n"
        "- engine.release.load_release_metadata\n",
        encoding="utf-8",
    )

    user_path.write_text(
        "# User Documentation\n\n"
        "## Quick Start\n"
        "1. Install dependencies with Poetry.\n"
        "2. Run `py -m poetry run python run.py`.\n"
        "3. Inspect logs under `logs/application.json`.\n",
        encoding="utf-8",
    )

    dev_path.write_text(
        "# Developer Documentation\n\n"
        "## Release Validation\n"
        "- Compile: `py -m poetry run python -m compileall engine run.py`\n"
        "- Startup: `py -m poetry run python run.py`\n"
        "- Tests: `py -m poetry run pytest`\n",
        encoding="utf-8",
    )

    architecture_path.write_text(
        "# Architecture\n\n"
        "The application follows service-oriented orchestration from run.main.\n"
        "Subsystem business logic remains inside engine packages.\n"
        "Release utilities live in engine.release and are side-effect free.\n",
        encoding="utf-8",
    )

    changelog_path.write_text(
        "# Changelog\n\n"
        f"## {metadata.version} - Release Candidate\n"
        "- Final startup, diagnostics, logging, and release validation pass.\n"
        "- Added release metadata, dependency validation, and documentation generation.\n",
        encoding="utf-8",
    )

    return [api_path, user_path, dev_path, architecture_path, changelog_path]
