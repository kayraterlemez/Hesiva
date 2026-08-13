import configparser
import runpy
import shutil
import tomllib
from pathlib import Path

import pytest
from PySide6.QtGui import QImage

from hesiva.database import startup
from hesiva.database.paths import get_application_data_directory
from hesiva.database.startup import DatabaseStartupError
from hesiva.resources import get_application_icon_path
from hesiva.version import get_application_version

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_migration_resource_directory_is_complete() -> None:
    migration_directory = startup.get_migration_directory()

    assert migration_directory.is_dir()
    assert all(
        (migration_directory / resource).exists()
        for resource in startup.REQUIRED_MIGRATION_RESOURCES
    )
    assert startup.get_migration_head() == "b46d1256c5f2"


def test_missing_frozen_migration_resources_fail_clearly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "MIGRATION_DIRECTORY", tmp_path)

    with pytest.raises(DatabaseStartupError, match="migration resources"):
        startup.get_migration_directory()


def test_build_data_contains_only_metadata_migrations_and_application_icon() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    data_sources = [Path(source) for source, _destination in support["hesiva_datas"]()]
    destinations = [destination for _source, destination in support["hesiva_datas"]()]

    assert data_sources[0] == REPOSITORY_ROOT / "src/hesiva/database/migrations"
    assert destinations[0] == "hesiva/database/migrations"
    assert data_sources[1] == REPOSITORY_ROOT / "assets/hesiva-icon.png"
    assert destinations[1] == "hesiva/assets"
    assert any(source.name.endswith((".dist-info", ".egg-info")) for source in data_sources[2:])
    assert all("tests" not in source.parts for source in data_sources)
    assert all(source.suffix not in {".db", ".exa", ".zip"} for source in data_sources)


def test_build_metadata_matches_authoritative_project_version() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))

    assert support["verify_build_metadata"]() == get_application_version()


def test_only_unavailable_unused_tiff_plugin_is_filtered() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    entries = [
        ("PySide6/Qt/plugins/imageformats/libqtiff.so", "/host/libqtiff.so", "BINARY"),
        ("PySide6/Qt/plugins/imageformats/libqjpeg.so", "/host/libqjpeg.so", "BINARY"),
        ("PySide6/Qt/plugins/platforms/libqxcb.so", "/host/libqxcb.so", "BINARY"),
    ]

    assert support["without_unused_qt_plugins"](entries) == entries[1:]


def test_host_hwcaps_libraries_are_replaced_with_baseline_variants(tmp_path: Path) -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    library_root = tmp_path / "lib64"
    optimized = library_root / "glibc-hwcaps/x86-64-v3/libexample.so"
    baseline = library_root / "libexample.so"
    optimized.parent.mkdir(parents=True)
    optimized.touch()
    baseline.touch()
    ordinary = ("ordinary.so", "/vendor/ordinary.so", "BINARY")

    assert support["with_baseline_linux_libraries"](
        [("libexample.so", str(optimized), "BINARY"), ordinary]
    ) == [("libexample.so", str(baseline), "BINARY"), ordinary]


def test_linux_data_path_is_independent_of_working_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_home = tmp_path / "xdg-data"
    unrelated_working_directory = tmp_path / "working-directory"
    unrelated_working_directory.mkdir()
    monkeypatch.chdir(unrelated_working_directory)

    assert (
        get_application_data_directory(
            platform_name="linux",
            environment={"XDG_DATA_HOME": str(data_home)},
            home_directory=tmp_path / "home",
        )
        == data_home / "hesiva"
    )


def test_runtime_version_matches_project_metadata() -> None:
    project = REPOSITORY_ROOT / "pyproject.toml"

    assert f'version = "{get_application_version()}"' in project.read_text(encoding="utf-8")


def test_mit_license_and_project_metadata_are_consistent() -> None:
    license_text = (REPOSITORY_ROOT / "LICENSE").read_text(encoding="utf-8")
    project = tomllib.loads((REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert license_text.startswith("MIT License\n\nCopyright (c) 2026 Kayra Terlemez\n")
    assert "Permission is hereby granted, free of charge" in license_text
    assert project["project"]["license"] == "MIT"
    assert project["project"]["license-files"] == ["LICENSE"]
    assert project["project"]["version"] == get_application_version()


@pytest.mark.parametrize("size", [16, 32, 48, 64, 128, 256, 512])
def test_master_and_generated_icons_have_expected_size_and_transparency(size: int) -> None:
    master = QImage(str(REPOSITORY_ROOT / "assets/hesiva-icon.png"))
    generated = QImage(
        str(REPOSITORY_ROOT / f"packaging/icons/hicolor/{size}x{size}/apps/hesiva.png")
    )

    assert not master.isNull()
    assert master.width() == master.height() == 2000
    assert master.hasAlphaChannel()
    assert master.pixelColor(0, 0).alpha() == 0
    assert master.pixelColor(1000, 1000).alpha() == 255
    assert not generated.isNull()
    assert generated.width() == generated.height() == size
    assert generated.hasAlphaChannel()
    assert generated.pixelColor(0, 0).alpha() == 0


def test_application_icon_resolves_in_source_and_packaged_layout(tmp_path: Path) -> None:
    source_icon = REPOSITORY_ROOT / "assets/hesiva-icon.png"
    assert get_application_icon_path() == source_icon

    package_directory = tmp_path / "hesiva"
    packaged_icon = package_directory / "assets/hesiva-icon.png"
    packaged_icon.parent.mkdir(parents=True)
    packaged_icon.write_bytes(source_icon.read_bytes())

    assert (
        get_application_icon_path(
            package_directory=package_directory,
            repository_root=tmp_path / "absent-source-root",
        )
        == packaged_icon
    )


def test_desktop_entry_and_launcher_use_installed_names() -> None:
    desktop_path = REPOSITORY_ROOT / "packaging/linux/hesiva.desktop"
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(desktop_path, encoding="utf-8")
    desktop = parser["Desktop Entry"]
    launcher = (REPOSITORY_ROOT / "packaging/linux/hesiva").read_text(encoding="utf-8")

    assert desktop["Type"] == "Application"
    assert desktop["Name"] == "Hesiva"
    assert desktop["Exec"] == "hesiva"
    assert desktop["Icon"] == "hesiva"
    assert desktop["Terminal"] == "false"
    assert desktop["Categories"] == "Office;Finance;"
    assert launcher == '#!/bin/sh\nexec /opt/hesiva/Hesiva "$@"\n'


def test_debian_metadata_and_build_layout_are_authoritative() -> None:
    control = (REPOSITORY_ROOT / "packaging/debian/control.in").read_text(encoding="utf-8")
    build_script = (REPOSITORY_ROOT / "scripts/build_deb.sh").read_text(encoding="utf-8")

    assert "Package: hesiva\n" in control
    assert "Version: @VERSION@\n" in control
    assert "Architecture: amd64\n" in control
    assert "Maintainer: Kayra Terlemez <kayraterlemez2@gmail.com>\n" in control
    assert "License:" not in control
    assert get_application_version() not in control
    assert "from hesiva.version import get_application_version" in build_script
    assert "--stage-only" in build_script
    for installed_path in (
        "opt/hesiva",
        "usr/bin/hesiva",
        "usr/share/applications/hesiva.desktop",
        "usr/share/icons/",
        "usr/share/doc/hesiva/LICENSE",
    ):
        assert installed_path in build_script
    assert "postrm" not in build_script
    assert "prerm" not in build_script
    assert ".local/share/hesiva" not in build_script
    assert "XDG_DATA_HOME" not in build_script


def _create_provenance_fixture(repository_root: Path) -> None:
    (repository_root / "src/hesiva").mkdir(parents=True)
    (repository_root / "src/hesiva/example.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repository_root / "assets").mkdir()
    (repository_root / "assets/hesiva-icon.png").write_bytes(b"synthetic-icon")
    (repository_root / "packaging").mkdir()
    (repository_root / "packaging/Hesiva.spec").write_text("# spec\n", encoding="utf-8")
    (repository_root / "packaging/pyinstaller_support.py").write_text(
        "# support\n",
        encoding="utf-8",
    )
    (repository_root / "packaging/icons/hicolor/16x16/apps").mkdir(parents=True)
    (repository_root / "packaging/icons/hesiva.ico").write_bytes(b"synthetic-windows-icon")
    (repository_root / "packaging/icons/hicolor/16x16/apps/hesiva.png").write_bytes(
        b"synthetic-linux-icon"
    )
    (repository_root / "packaging/linux").mkdir()
    (repository_root / "packaging/linux/hesiva").write_text("#!/bin/sh\n", encoding="utf-8")
    (repository_root / "packaging/debian").mkdir()
    (repository_root / "packaging/debian/control.in").write_text(
        "Package: hesiva\n",
        encoding="utf-8",
    )
    (repository_root / "LICENSE").write_text("Synthetic fixture license\n", encoding="utf-8")
    (repository_root / "pyproject.toml").write_text(
        '[project]\nname = "hesiva"\nversion = "0.1.0"\n',
        encoding="utf-8",
    )


def test_frozen_artifact_provenance_rejects_source_and_runtime_drift(tmp_path: Path) -> None:
    provenance = runpy.run_path(str(REPOSITORY_ROOT / "packaging/artifact_provenance.py"))
    repository_root = tmp_path / "repository"
    _create_provenance_fixture(repository_root)
    runtime = repository_root / "dist/Hesiva"
    runtime.mkdir(parents=True)
    executable = runtime / "Hesiva"
    executable.write_bytes(b"frozen-runtime")
    executable.chmod(0o755)
    manifest = repository_root / "dist/Hesiva.provenance.json"

    expected_source = provenance["source_digest"](repository_root)
    provenance["record_manifest"](
        expected_source_sha256=expected_source,
        repository_root=repository_root,
        runtime_path=runtime,
        manifest_path=manifest,
    )
    provenance["verify_manifest"](
        repository_root=repository_root,
        runtime_path=runtime,
        manifest_path=manifest,
    )

    icon_mutations = (
        (repository_root / "packaging/icons/hesiva.ico", b"changed-windows-icon"),
        (
            repository_root / "packaging/icons/hicolor/16x16/apps/hesiva.png",
            b"changed-linux-icon",
        ),
    )
    for icon_path, changed_content in icon_mutations:
        original_content = icon_path.read_bytes()
        icon_path.write_bytes(changed_content)
        with pytest.raises(provenance["ProvenanceError"], match="stale source"):
            provenance["verify_manifest"](
                repository_root=repository_root,
                runtime_path=runtime,
                manifest_path=manifest,
            )
        icon_path.write_bytes(original_content)

    staged_runtime = tmp_path / "staged-runtime"
    shutil.copytree(runtime, staged_runtime, symlinks=True)
    provenance["verify_manifest"](
        repository_root=repository_root,
        runtime_path=staged_runtime,
        manifest_path=manifest,
    )

    (repository_root / "src/hesiva/example.py").write_text("VALUE = 2\n", encoding="utf-8")
    with pytest.raises(provenance["ProvenanceError"], match="stale source"):
        provenance["verify_manifest"](
            repository_root=repository_root,
            runtime_path=runtime,
            manifest_path=manifest,
        )

    (repository_root / "src/hesiva/example.py").write_text("VALUE = 1\n", encoding="utf-8")
    executable.write_bytes(b"substituted-runtime")
    with pytest.raises(provenance["ProvenanceError"], match="contents differ"):
        provenance["verify_manifest"](
            repository_root=repository_root,
            runtime_path=runtime,
            manifest_path=manifest,
        )


def test_build_provenance_rejects_source_changes_during_build(tmp_path: Path) -> None:
    provenance = runpy.run_path(str(REPOSITORY_ROOT / "packaging/artifact_provenance.py"))
    repository_root = tmp_path / "repository"
    _create_provenance_fixture(repository_root)
    runtime = repository_root / "dist/Hesiva"
    runtime.mkdir(parents=True)
    (runtime / "Hesiva").write_bytes(b"frozen-runtime")
    manifest = repository_root / "dist/Hesiva.provenance.json"
    source_before_build = provenance["source_digest"](repository_root)

    (repository_root / "src/hesiva/example.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(provenance["ProvenanceError"], match="changed while"):
        provenance["record_manifest"](
            expected_source_sha256=source_before_build,
            repository_root=repository_root,
            runtime_path=runtime,
            manifest_path=manifest,
        )
    assert not manifest.exists()


@pytest.mark.parametrize("preexisting_manifest", (None, b"previous manifest\n"))
def test_build_provenance_rechecks_source_after_hashing_runtime(
    tmp_path: Path,
    preexisting_manifest: bytes | None,
) -> None:
    provenance = runpy.run_path(str(REPOSITORY_ROOT / "packaging/artifact_provenance.py"))
    repository_root = tmp_path / "repository"
    _create_provenance_fixture(repository_root)
    runtime = repository_root / "dist/Hesiva"
    runtime.mkdir(parents=True)
    (runtime / "Hesiva").write_bytes(b"frozen-runtime")
    manifest = repository_root / "dist/Hesiva.provenance.json"
    if preexisting_manifest is not None:
        manifest.write_bytes(preexisting_manifest)
    source_path = repository_root / "src/hesiva/example.py"
    source_before_build = provenance["source_digest"](repository_root)
    real_runtime_digest = provenance["runtime_digest"]

    def mutate_source_after_runtime_hash(runtime_path: Path) -> str:
        digest = real_runtime_digest(runtime_path)
        source_path.write_text("VALUE = 2\n", encoding="utf-8")
        return digest

    provenance["record_manifest"].__globals__["runtime_digest"] = mutate_source_after_runtime_hash

    with pytest.raises(provenance["ProvenanceError"], match="provenance was being recorded"):
        provenance["record_manifest"](
            expected_source_sha256=source_before_build,
            repository_root=repository_root,
            runtime_path=runtime,
            manifest_path=manifest,
        )

    if preexisting_manifest is None:
        assert not manifest.exists()
    else:
        assert manifest.read_bytes() == preexisting_manifest


def test_release_scripts_require_and_preserve_verified_artifact_provenance() -> None:
    linux_build = (REPOSITORY_ROOT / "scripts/build_linux.sh").read_text(encoding="utf-8")
    debian_build = (REPOSITORY_ROOT / "scripts/build_deb.sh").read_text(encoding="utf-8")
    smoke = (REPOSITORY_ROOT / "scripts/smoke_packaged_linux.sh").read_text(encoding="utf-8")

    assert linux_build.index("artifact_provenance.py invalidate") < linux_build.index(
        "-m PyInstaller"
    )
    assert linux_build.index("-m PyInstaller") < linux_build.index("artifact_provenance.py record")
    assert linux_build.index("artifact_provenance.py record") < linux_build.index(
        "artifact_provenance.py verify"
    )
    assert "Kullanım: scripts/build_linux.sh [--build-only]" in linux_build
    first_verification = debian_build.index("artifact_provenance.py verify")
    runtime_copy = debian_build.index('cp -a "$runtime_source/."')
    staged_verification = debian_build.index(
        "artifact_provenance.py verify",
        first_verification + 1,
    )
    assert first_verification < runtime_copy < staged_verification
    assert 'if [[ ! -x "$runtime_source/Hesiva"' not in debian_build
    assert smoke.count("artifact_provenance.py verify") == 2
    assert "QT_LOGGING_RULES='qt.qpa.backingstore=true'" in smoke
    assert "grep -q '^qt.qpa.backingstore:'" in smoke
    assert "Hesiva authenticated startup failed" in smoke
    assert "PRAGMA integrity_check" in smoke
    assert "SELECT version_num FROM alembic_version" in smoke

    runtime_smoke = (REPOSITORY_ROOT / "packaging/runtime_smoke.py").read_text(encoding="utf-8")
    assert "configure_application_theme(application)" in runtime_smoke
    assert 'application.setStyleSheet("")' in runtime_smoke
    assert 'application.style().objectName().casefold() == "fusion"' in runtime_smoke


def test_packaging_sources_contain_no_developer_home_path() -> None:
    text_files = [
        *REPOSITORY_ROOT.joinpath("packaging").rglob("*.py"),
        *REPOSITORY_ROOT.joinpath("packaging").rglob("*.spec"),
        *REPOSITORY_ROOT.joinpath("packaging").rglob("*.desktop"),
        REPOSITORY_ROOT / "packaging/linux/hesiva",
        *REPOSITORY_ROOT.joinpath("packaging/debian").rglob("*.in"),
        *REPOSITORY_ROOT.joinpath("scripts").glob("*.sh"),
    ]

    assert all("/home/hiw" not in path.read_text(encoding="utf-8") for path in text_files)
