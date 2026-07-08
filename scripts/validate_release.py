from __future__ import annotations

from engine.release.dependencies import validate_runtime_dependencies
from engine.release.diagnostics import collect_runtime_diagnostics
from engine.release.metadata import load_release_metadata


def main() -> None:
    metadata = load_release_metadata()
    deps = validate_runtime_dependencies()
    diagnostics = collect_runtime_diagnostics()

    print(f"app={metadata.app_name}")
    print(f"version={metadata.version}")
    print(f"channel={metadata.release_channel}")
    print(f"missing_dependencies={len(deps.missing)}")
    print(f"active_threads={diagnostics.active_threads}")
    print(f"memory_current_bytes={diagnostics.traced_memory_current_bytes}")


if __name__ == "__main__":
    main()
