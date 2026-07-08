from __future__ import annotations

from pathlib import Path

from engine.release.documentation import generate_release_documents
from engine.release.metadata import load_release_metadata


def main() -> None:
    root = Path.cwd()
    metadata = load_release_metadata()
    generated = generate_release_documents(root=root, metadata=metadata)
    for path in generated:
        print(f"generated: {path}")


if __name__ == "__main__":
    main()
