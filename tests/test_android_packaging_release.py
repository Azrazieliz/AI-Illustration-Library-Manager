from __future__ import annotations

import json
from pathlib import Path

from engine.android import AndroidBridge


ROOT = Path(__file__).resolve().parent.parent
ANDROID_ROOT = ROOT / "android_app"
RELEASE_ROOT = ROOT / "release" / "android"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(_read(path))


def test_android_bridge_baseline_available() -> None:
    assert callable(getattr(AndroidBridge, "search"))
    assert callable(getattr(AndroidBridge, "advancedSearch"))


def test_ui_navigation_declares_all_required_screens() -> None:
    destination_file = ANDROID_ROOT / "app/src/main/java/com/ailm/android/ui/navigation/AppDestination.kt"
    content = _read(destination_file)

    required = [
        "Splash",
        "FirstLaunchWizard",
        "Dashboard",
        "LibraryBrowser",
        "FolderBrowser",
        "ImageViewer",
        "RecognitionResults",
        "ReviewQueue",
        "Search",
        "AdvancedSearch",
        "SemanticSearch",
        "CharacterPage",
        "SeriesPage",
        "Collections",
        "Tags",
        "BulkOperations",
        "KnowledgePacks",
        "Downloads",
        "Automation",
        "PluginManager",
        "Statistics",
        "Logs",
        "Settings",
        "About",
    ]
    for route in required:
        assert route in content


def test_first_launch_wizard_plan_is_resumable_and_complete() -> None:
    wizard_plan = _read_json(ANDROID_ROOT / "app/src/main/assets/first_launch_plan.json")
    steps = wizard_plan["steps"]

    assert wizard_plan["resumable"] is True
    assert len(steps) == 11
    assert steps[0] == "Welcome"
    assert steps[-1] == "Finish"


def test_download_model_and_storage_capabilities_declared() -> None:
    model_caps = _read_json(ANDROID_ROOT / "app/src/main/assets/model_manager_capabilities.json")
    storage_caps = _read_json(ANDROID_ROOT / "app/src/main/assets/storage_support.json")

    assert set(model_caps["supports"]) == {"recognition_models", "embedding_models", "future_models"}
    assert {"pause", "resume", "retry", "checksum_verification"}.issubset(set(model_caps["operations"]))

    required_storage = {
        "SAF",
        "MediaStore",
        "Tree URI",
        "DocumentProvider",
        "Internal storage",
        "SD card",
        "NAS",
        "SMB",
        "FTP",
        "SFTP",
        "WebDAV",
    }
    assert required_storage.issubset(set(storage_caps["android_storage"]))
    assert storage_caps["integration"] == "backend_adapters_only"


def test_review_search_collections_and_settings_features_present() -> None:
    screens_file = _read(ANDROID_ROOT / "app/src/main/java/com/ailm/android/ui/screens/Screens.kt")

    expected_terms = [
        "Review Queue",
        "Approve",
        "Reject",
        "Undo",
        "Search",
        "Advanced Search",
        "Semantic Search",
        "Collections",
        "Settings",
        "Knowledge Packs",
        "Downloads",
    ]
    for term in expected_terms:
        assert term in screens_file


def test_background_workers_declared_for_setup_and_downloads() -> None:
    workers_file = _read(ANDROID_ROOT / "app/src/main/java/com/ailm/android/workers/SetupWorkers.kt")
    assert "InitialSetupWorker" in workers_file
    assert "ModelDownloadWorker" in workers_file
    assert "Result.success()" in workers_file


def test_packaging_configuration_files_exist() -> None:
    expected_files = [
        ANDROID_ROOT / "settings.gradle.kts",
        ANDROID_ROOT / "build.gradle.kts",
        ANDROID_ROOT / "app/build.gradle.kts",
        ANDROID_ROOT / "app/proguard-rules.pro",
        ANDROID_ROOT / "app/src/main/AndroidManifest.xml",
        RELEASE_ROOT / "version-manifest.json",
        RELEASE_ROOT / "release-metadata.json",
        RELEASE_ROOT / "installer-metadata.json",
        RELEASE_ROOT / "dependency-report.txt",
        RELEASE_ROOT / "release-validation.json",
        RELEASE_ROOT / "startup-diagnostics.json",
        RELEASE_ROOT / "health-checks.json",
    ]

    for path in expected_files:
        assert path.exists(), f"missing required file: {path}"


def test_release_version_and_channel_are_stable_2_0_0() -> None:
    version_manifest = _read_json(RELEASE_ROOT / "version-manifest.json")
    release_metadata = _read_json(RELEASE_ROOT / "release-metadata.json")
    validation = _read_json(RELEASE_ROOT / "release-validation.json")

    assert version_manifest["version"] == "2.0.0"
    assert release_metadata["release_version"] == "2.0.0"
    assert release_metadata["release_channel"] == "stable"
    assert validation["validated"] is True


def test_installation_flow_and_artifact_presence() -> None:
    installer_metadata = _read_json(RELEASE_ROOT / "installer-metadata.json")
    apk_path = RELEASE_ROOT / "artifacts" / "ailm-android-2.0.0-release.apk"
    aab_path = RELEASE_ROOT / "artifacts" / "ailm-android-2.0.0-release.aab"

    assert installer_metadata["supports_upgrade"] is True
    assert installer_metadata["supports_fresh_install"] is True
    assert installer_metadata["first_run_wizard_required"] is True
    assert apk_path.exists()
    assert aab_path.exists()
