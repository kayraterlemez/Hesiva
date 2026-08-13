import configparser
import hashlib
import json
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


def test_required_linux_release_libraries_are_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    resolved = {
        "libxcb-cursor.so.0": "/system/libxcb-cursor.so.0",
        "libcups.so.2": "/system/libcups.so.2",
    }
    support["required_linux_binaries"].__globals__["resolve_library_path"] = resolved.get
    monkeypatch.setattr(support["required_linux_binaries"].__globals__["sys"], "platform", "linux")

    assert support["required_linux_binaries"]() == [
        ("/system/libxcb-cursor.so.0", "."),
        ("/system/libcups.so.2", "."),
    ]

    resolved.pop("libxcb-cursor.so.0")
    with pytest.raises(RuntimeError, match="libxcb-cursor.so.0"):
        support["required_linux_binaries"]()


def test_unused_tiff_and_gpl_only_virtual_keyboard_payloads_are_filtered() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))
    entries = [
        ("PySide6/Qt/plugins/imageformats/libqtiff.so", "/host/libqtiff.so", "BINARY"),
        (
            "PySide6/Qt/plugins/platforminputcontexts/libqtvirtualkeyboardplugin.so",
            "/wheel/libqtvirtualkeyboardplugin.so",
            "BINARY",
        ),
        (
            "PySide6/Qt/lib/libQt6VirtualKeyboard.so.6",
            "/wheel/libQt6VirtualKeyboard.so.6",
            "BINARY",
        ),
        (
            "libQt6VirtualKeyboardQml.so.6",
            "/wheel/libQt6VirtualKeyboardQml.so.6",
            "SYMLINK",
        ),
        (
            "PySide6/Qt/plugins/platforminputcontexts/qtvirtualkeyboardplugin.dll",
            r"C:\\wheel\\qtvirtualkeyboardplugin.dll",
            "BINARY",
        ),
        (
            "PySide6/Qt/bin/Qt6VirtualKeyboard.dll",
            r"C:\\wheel\\Qt6VirtualKeyboard.dll",
            "BINARY",
        ),
        (
            "PySide6/Qt/lib/libQt6Qml.so.6",
            "/wheel/libQt6Qml.so.6",
            "BINARY",
        ),
        ("Qt6Quick.dll", r"C:\\wheel\\Qt6Quick.dll", "BINARY"),
        ("PySide6/Qt/plugins/imageformats/libqjpeg.so", "/host/libqjpeg.so", "BINARY"),
        ("PySide6/Qt/plugins/platforms/libqxcb.so", "/host/libqxcb.so", "BINARY"),
    ]

    assert support["without_unused_qt_plugins"](entries) == entries[-2:]


def test_qt_filter_applies_to_binary_and_symlink_collections() -> None:
    spec_text = (REPOSITORY_ROOT / "packaging" / "Hesiva.spec").read_text(encoding="utf-8")

    assert "without_unused_qt_plugins(analysis.binaries)" in spec_text
    assert "analysis.datas = without_unused_qt_plugins(analysis.datas)" in spec_text


def test_windowed_build_excludes_optional_gpl_readline_runtime() -> None:
    support = runpy.run_path(str(REPOSITORY_ROOT / "packaging" / "pyinstaller_support.py"))

    assert "readline" in support["DEVELOPMENT_EXCLUDES"]


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


def _load_license_inventory() -> dict[str, object]:
    return runpy.run_path(str(REPOSITORY_ROOT / "packaging/license_inventory.py"))


def test_exact_third_party_legal_corpus_is_present_and_version_locked() -> None:
    licensing = _load_license_inventory()
    policy = licensing["verify_build_environment"]()

    assert policy["application_version"] == get_application_version()
    assert policy["qt_version"] == "6.11.1"
    assert policy["cpython_version"] == "3.13.14"
    assert (REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md").is_file()
    assert (REPOSITORY_ROOT / "SOURCE-OFFER.md").is_file()
    assert (REPOSITORY_ROOT / "RELINKING.md").is_file()
    assert (REPOSITORY_ROOT / "licenses/Qt-6.11.1/LGPL-3.0-only.txt").stat().st_size > 1000
    assert (REPOSITORY_ROOT / "licenses/CPython-3.13.14/LICENSE.txt").stat().st_size > 1000
    assert (REPOSITORY_ROOT / "licenses/PyInstaller-6.22.0/COPYING.txt").stat().st_size > 1000
    assert len(list((REPOSITORY_ROOT / "licenses/Qt-6.11.1/third-party").glob("*.html"))) > 50
    source_requirements = json.loads(
        (REPOSITORY_ROOT / "packaging/lgpl-source-requirements.json").read_text(encoding="utf-8")
    )
    source_names = {entry["filename"] for entry in source_requirements["required_archives"]}
    assert "qtwebengine-everywhere-src-6.11.1.tar.xz" in source_names
    assert "pyside-setup-everywhere-src-6.11.1.tar.xz" in source_names
    assert not any("virtualkeyboard" in name.casefold() for name in source_names)
    assert all(
        len(entry["sha256"]) == 64 and entry["size"] > 0
        for entry in source_requirements["required_archives"]
    )


def test_license_policy_rejects_dependency_version_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    licensing = _load_license_inventory()
    real_version = licensing["verify_build_environment"].__globals__["importlib"].metadata.version

    def drifted_version(name: str) -> str:
        return "99.0" if name == "PySide6" else real_version(name)

    monkeypatch.setattr(
        licensing["verify_build_environment"].__globals__["importlib"].metadata,
        "version",
        drifted_version,
    )

    with pytest.raises(licensing["LicenseInventoryError"], match="version drift: PySide6"):
        licensing["verify_build_environment"]()


@pytest.mark.parametrize("under_internal", [False, True])
def test_collect_destination_resolves_supported_onedir_layouts(
    tmp_path: Path,
    under_internal: bool,
) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    destination = Path("PySide6/Qt/lib/libQt6Core.so.6")
    expected = runtime / destination
    if under_internal:
        expected = runtime / "_internal" / destination
    expected.parent.mkdir(parents=True)
    expected.write_bytes(b"synthetic Qt library")

    resolved = licensing["_resolve_collect_destination"](runtime, destination.as_posix())

    assert resolved == expected


def test_collect_destination_rejects_ambiguous_onedir_layout(tmp_path: Path) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    destination = Path("PySide6/Qt/lib/libQt6Core.so.6")
    root_entry = runtime / destination
    internal_entry = runtime / "_internal" / destination
    root_entry.parent.mkdir(parents=True)
    internal_entry.parent.mkdir(parents=True)
    root_entry.write_bytes(b"root")
    internal_entry.write_bytes(b"internal")

    with pytest.raises(licensing["LicenseInventoryError"], match="entry is ambiguous"):
        licensing["_resolve_collect_destination"](runtime, destination.as_posix())


def test_collect_destination_preserves_absent_entry_error(tmp_path: Path) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    runtime.mkdir()
    destination = "PySide6/Qt/lib/libQt6Core.so.6"

    with pytest.raises(
        licensing["LicenseInventoryError"],
        match=f"entry is absent from frozen runtime: {destination}",
    ):
        licensing["_resolve_collect_destination"](runtime, destination)


def test_collect_destination_preserves_dangling_symlink_entries(tmp_path: Path) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    entry = runtime / "_internal/libQt6Core.so.6"
    entry.parent.mkdir(parents=True)
    entry.symlink_to("PySide6/Qt/lib/libQt6Core.so.6")

    resolved = licensing["_resolve_collect_destination"](runtime, "libQt6Core.so.6")

    assert resolved == entry
    assert resolved.is_symlink()


def test_native_inventory_records_resolved_internal_runtime_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    runtime_entry = runtime / "_internal/libnative.so.1"
    runtime_entry.parent.mkdir(parents=True)
    runtime_entry.write_bytes(b"native")
    source = tmp_path / "host/libnative.so.1"
    source.parent.mkdir()
    source.write_bytes(b"host native")
    copyright_file = tmp_path / "copyright"
    copyright_file.write_text("Synthetic copyright\n", encoding="utf-8")
    monkeypatch.setattr(
        licensing["_native_debian_inventory"].__globals__["shutil"],
        "which",
        lambda _name: "/usr/bin/dpkg-query",
    )
    monkeypatch.setitem(
        licensing["_native_debian_inventory"].__globals__,
        "_debian_owner",
        lambda _source: {
            "binary_package": "libnative1:amd64",
            "binary_version": "1.0-1",
            "source_package": "native",
            "source_version": "1.0-1",
            "copyright_path": str(copyright_file),
        },
    )

    packages, _copyright_files = licensing["_native_debian_inventory"](
        [("libnative.so.1", str(source), "BINARY", runtime_entry)],
        REPOSITORY_ROOT,
        runtime,
    )

    assert packages[0]["runtime_entries"] == ["_internal/libnative.so.1"]


def test_native_debian_inventory_resolves_source_before_owner_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    licensing = _load_license_inventory()

    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    runtime = tmp_path / "runtime"
    runtime.mkdir()

    real_library = tmp_path / "usr/lib/libexample.so.1"
    real_library.parent.mkdir(parents=True)
    real_library.write_bytes(b"library")

    symlink = tmp_path / "lib/libexample.so.1"
    symlink.parent.mkdir(parents=True)
    symlink.symlink_to(real_library)

    runtime_library = runtime / "_internal/libexample.so.1"
    runtime_library.parent.mkdir(parents=True)
    runtime_library.write_bytes(b"bundled")

    observed: list[Path] = []

    def fake_owner(path: Path) -> dict[str, str]:
        observed.append(path)
        return {
            "binary_package": "libexample1:amd64",
            "binary_version": "1.0",
            "source_package": "example",
            "source_version": "1.0",
            "copyright_path": str(tmp_path / "copyright"),
        }

    (tmp_path / "copyright").write_text("license", encoding="utf-8")

    globals_ = licensing["_native_debian_inventory"].__globals__
    monkeypatch.setitem(globals_, "_debian_owner", fake_owner)
    monkeypatch.setattr(
        globals_["shutil"],
        "which",
        lambda _name: "/usr/bin/dpkg-query",
    )
    monkeypatch.setattr(
        globals_["sys"],
        "prefix",
        str(tmp_path / "venv"),
    )

    entries = [
        (
            "libexample.so.1",
            str(symlink),
            "BINARY",
            runtime_library,
        )
    ]

    licensing["_native_debian_inventory"](
        entries,
        repository_root,
        runtime,
    )

    assert observed == [real_library.resolve()]


def test_runtime_legal_inventory_is_tied_to_exact_frozen_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    (runtime / "_internal").mkdir(parents=True)
    (runtime / "Hesiva").write_bytes(b"synthetic executable")
    toc = tmp_path / "COLLECT-00.toc"
    toc.write_text("([('Hesiva', '/synthetic/libhesiva.so', 'BINARY')],)\n", encoding="utf-8")
    copyright_file = tmp_path / "copyright"
    copyright_file.write_text("Authoritative synthetic package copyright\n", encoding="utf-8")
    native_record = {
        "binary_package": "libsynthetic1:amd64",
        "binary_version": "1.2.3-1",
        "source_package": "synthetic",
        "source_version": "1.2.3-1",
        "runtime_entries": ["Hesiva"],
    }
    monkeypatch.setitem(
        licensing["stage_linux_runtime"].__globals__,
        "_native_debian_inventory",
        lambda _entries, _repository_root, _runtime: (
            [native_record],
            {"libsynthetic1_amd64": copyright_file},
        ),
    )

    inventory = licensing["stage_linux_runtime"](
        runtime,
        toc,
        repository_root=REPOSITORY_ROOT,
    )

    assert inventory["native_debian_packages"] == [native_record]
    assert (runtime / "THIRD_PARTY_NOTICES.md").is_file()
    assert (runtime / "licenses/Native-Debian/libsynthetic1_amd64/copyright").is_file()
    licensing["verify_runtime"](runtime, repository_root=REPOSITORY_ROOT)
    with pytest.raises(licensing["LicenseInventoryError"], match="license/source review"):
        licensing["verify_runtime"](
            runtime,
            repository_root=REPOSITORY_ROOT,
            require_redistribution=True,
        )

    staged_notice = runtime / "THIRD_PARTY_NOTICES.md"
    approved_notice = staged_notice.read_bytes()
    staged_notice.write_bytes(b"stale notices")
    with pytest.raises(licensing["LicenseInventoryError"], match="legal corpus differs"):
        licensing["verify_runtime"](runtime, repository_root=REPOSITORY_ROOT)
    staged_notice.write_bytes(approved_notice)

    (runtime / "Hesiva").write_bytes(b"different executable")
    with pytest.raises(licensing["LicenseInventoryError"], match="different runtime payload"):
        licensing["verify_runtime"](runtime, repository_root=REPOSITORY_ROOT)


def test_runtime_legal_staging_rejects_forbidden_qt_component(
    tmp_path: Path,
) -> None:
    licensing = _load_license_inventory()
    runtime = tmp_path / "Hesiva"
    forbidden = runtime / "_internal/PySide6/Qt/lib/libQt6VirtualKeyboard.so.6"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_bytes(b"forbidden")
    toc = tmp_path / "COLLECT-00.toc"
    toc.write_text("([], )\n", encoding="utf-8")

    with pytest.raises(licensing["LicenseInventoryError"], match="Forbidden GPL-only"):
        licensing["stage_linux_runtime"](
            runtime,
            toc,
            repository_root=REPOSITORY_ROOT,
        )


def test_lgpl_source_companion_is_exact_and_fail_closed(tmp_path: Path) -> None:
    licensing = _load_license_inventory()
    repository = tmp_path / "repository"
    (repository / "packaging").mkdir(parents=True)
    (repository / "RELINKING.md").write_bytes(b"Synthetic relinking instructions\n")
    source_payload = b"official synthetic source archive"
    requirements = {
        "application_version": "0.1.0",
        "format_version": 1,
        "qt_version": "6.11.1",
        "required_archives": [
            {
                "filename": "qtbase-everywhere-src-6.11.1.tar.xz",
                "sha256": hashlib.sha256(source_payload).hexdigest(),
                "size": len(source_payload),
                "url": "https://download.qt.io/official_releases/example",
            }
        ],
    }
    requirements_path = repository / "packaging/lgpl-source-requirements.json"
    requirements_path.write_text(json.dumps(requirements), encoding="utf-8")
    release = tmp_path / "release"
    release.mkdir()
    archive = release / "hesiva-0.1.0-lgpl-corresponding-source.tar.xz"
    source_directory = tmp_path / "sources"
    source_directory.mkdir()
    source_file = source_directory / "qtbase-everywhere-src-6.11.1.tar.xz"
    source_file.write_bytes(source_payload)
    assert (
        licensing["build_source_bundle"](
            source_directory,
            release,
            repository_root=repository,
        )
        == archive
    )

    assert (
        licensing["verify_source_bundle"](
            release,
            repository_root=repository,
        )
        == archive
    )

    source_file.write_bytes(b"changed source")
    with pytest.raises(licensing["LicenseInventoryError"], match="does not match Qt metadata"):
        licensing["build_source_bundle"](
            source_directory,
            release,
            repository_root=repository,
        )
    assert licensing["verify_source_bundle"](release, repository_root=repository) == archive


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
    assert "Depends: @DEPENDS@\n" in control
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
        "usr/share/doc/hesiva/THIRD_PARTY_NOTICES.md",
        "usr/share/doc/hesiva/SOURCE-OFFER.md",
        "usr/share/doc/hesiva/RELINKING.md",
        "usr/share/doc/hesiva/licenses",
        "usr/share/doc/hesiva/third-party-runtime-inventory.json",
        "usr/share/doc/hesiva/runtime-dependencies.txt",
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
    (repository_root / "packaging/linux_runtime_audit.py").write_text(
        "# dependency audit\n",
        encoding="utf-8",
    )
    (repository_root / "packaging/license_inventory.py").write_text(
        "# license audit\n",
        encoding="utf-8",
    )
    (repository_root / "packaging/license-policy.json").write_text("{}\n", encoding="utf-8")
    (repository_root / "packaging/lgpl-source-requirements.json").write_text(
        "{}\n", encoding="utf-8"
    )
    (repository_root / "packaging/native-license-approvals.json").write_text(
        "{}\n", encoding="utf-8"
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
    (repository_root / "THIRD_PARTY_NOTICES.md").write_text("Notices\n", encoding="utf-8")
    (repository_root / "SOURCE-OFFER.md").write_text("Sources\n", encoding="utf-8")
    (repository_root / "RELINKING.md").write_text("Relinking\n", encoding="utf-8")
    (repository_root / "licenses").mkdir()
    (repository_root / "licenses/example.txt").write_text("Example\n", encoding="utf-8")
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
        (repository_root / "licenses/example.txt", b"changed-legal-corpus"),
        (repository_root / "THIRD_PARTY_NOTICES.md", b"changed-notices"),
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
    assert linux_build.index("-m PyInstaller") < linux_build.index(
        "license_inventory.py stage-linux"
    )
    assert linux_build.index("license_inventory.py stage-linux") < linux_build.index(
        "artifact_provenance.py record"
    )
    assert linux_build.index("license_inventory.py verify-source-bundle") < linux_build.index(
        "artifact_provenance.py record"
    )
    assert linux_build.index("-m PyInstaller") < linux_build.index("linux_runtime_audit.py verify")
    assert linux_build.index("linux_runtime_audit.py verify") < linux_build.index(
        "artifact_provenance.py record"
    )
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
    assert "linux_runtime_audit.py debian-depends" in debian_build
    assert "license_inventory.py verify-runtime" in debian_build
    assert "license_inventory.py verify-source-bundle" in debian_build
    assert "s/@DEPENDS@/$dependency_list/g" in debian_build
    assert 'if [[ ! -x "$runtime_source/Hesiva"' not in debian_build
    assert smoke.count("artifact_provenance.py verify") == 2
    assert smoke.count("license_inventory.py verify-runtime") == 2
    assert "linux_runtime_audit.py verify" in smoke
    assert 'smoke_platform="${HESIVA_SMOKE_QPA_PLATFORM:-offscreen}"' in smoke
    assert "offscreen|xcb|wayland" in smoke
    assert smoke.count('QT_QPA_PLATFORM="$smoke_platform"') == 2
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


def _load_runtime_audit() -> dict[str, object]:
    return runpy.run_path(str(REPOSITORY_ROOT / "packaging/linux_runtime_audit.py"))


def _create_runtime_policy_fixture(runtime: Path) -> None:
    required = (
        "Hesiva",
        "_internal/libxcb-cursor.so.0",
        "_internal/libcups.so.2",
        "_internal/PySide6/Qt/plugins/platforms/libqxcb.so",
        "_internal/PySide6/Qt/plugins/platforms/libqwayland.so",
        "_internal/PySide6/Qt/plugins/printsupport/libcupsprintersupport.so",
    )
    for relative in required:
        path = runtime / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic")


def test_runtime_audit_models_pyinstaller_loader_resolution(tmp_path: Path) -> None:
    audit = _load_runtime_audit()
    runtime = tmp_path / "Hesiva"
    bundled = runtime / "_internal/libxcb-cursor.so.0"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"library")
    host = tmp_path / "host/libGL.so.1"
    host.parent.mkdir()
    host.write_bytes(b"library")

    resolutions = audit["_parse_ldd"](
        f"""
        linux-vdso.so.1 (0x0000)
        libxcb-cursor.so.0 => {bundled} (0x0001)
        libGL.so.1 => {host} (0x0002)
        libmissing.so.1 => not found
        /lib64/ld-linux-x86-64.so.2 (0x0003)
        """,
        runtime_root=runtime.resolve(),
    )

    assert [(item.soname, item.location) for item in resolutions] == [
        ("libxcb-cursor.so.0", "bundled"),
        ("libGL.so.1", "host"),
        ("libmissing.so.1", "missing"),
        ("ld-linux-x86-64.so.2", "host"),
    ]


def test_runtime_audit_rejects_unresolved_and_forbidden_components(
    tmp_path: Path,
) -> None:
    audit = _load_runtime_audit()
    runtime = tmp_path / "Hesiva"
    _create_runtime_policy_fixture(runtime)
    forbidden = runtime / "_internal/PySide6/Qt/lib/libQt6VirtualKeyboard.so.6"
    forbidden.parent.mkdir(parents=True, exist_ok=True)
    forbidden.write_bytes(b"forbidden")

    with pytest.raises(audit["RuntimeAuditError"], match="Forbidden release component"):
        audit["_validate_tree"](runtime)

    forbidden.unlink()
    audit["audit_runtime"].__globals__["_is_elf"] = lambda path: path.name == "Hesiva"
    audit["audit_runtime"].__globals__["_inspect_dynamic_section"] = lambda _path: (
        ("libmissing.so.1",),
        (),
        ("$ORIGIN/_internal",),
    )
    missing = audit["Resolution"]("libmissing.so.1", None, "missing")
    audit["audit_runtime"].__globals__["_inspect_resolutions"] = lambda *_args, **_kwargs: (
        missing,
    )

    with pytest.raises(audit["RuntimeAuditError"], match="unresolved ELF dependencies"):
        audit["audit_runtime"](runtime)


def test_runtime_audit_rejects_unreviewed_host_dependency(tmp_path: Path) -> None:
    audit = _load_runtime_audit()
    runtime = tmp_path / "Hesiva"
    _create_runtime_policy_fixture(runtime)
    audit["audit_runtime"].__globals__["_is_elf"] = lambda path: path.name == "Hesiva"
    audit["audit_runtime"].__globals__["_inspect_dynamic_section"] = lambda _path: (
        ("libxcb-cursor.so.0", "libcups.so.2", "libsurprise.so.1"),
        (),
        (),
    )
    audit["audit_runtime"].__globals__["_inspect_resolutions"] = lambda *_args, **_kwargs: (
        audit["Resolution"](
            "libxcb-cursor.so.0",
            str((runtime / "_internal/libxcb-cursor.so.0").resolve()),
            "bundled",
        ),
        audit["Resolution"](
            "libcups.so.2",
            str((runtime / "_internal/libcups.so.2").resolve()),
            "bundled",
        ),
        audit["Resolution"]("libsurprise.so.1", "/system/libsurprise.so.1", "host"),
    )

    with pytest.raises(audit["RuntimeAuditError"], match="unreviewed host dependencies"):
        audit["audit_runtime"](runtime)


def test_runtime_report_uses_only_direct_needed_edges_for_host_dependencies(
    tmp_path: Path,
) -> None:
    audit = _load_runtime_audit()
    runtime = tmp_path / "Hesiva"
    _create_runtime_policy_fixture(runtime)
    audit["audit_runtime"].__globals__["_is_elf"] = lambda path: path.name == "Hesiva"
    audit["audit_runtime"].__globals__["_inspect_dynamic_section"] = lambda _path: (
        ("libxcb-cursor.so.0", "libcups.so.2", "libEGL.so.1"),
        (),
        (),
    )
    audit["audit_runtime"].__globals__["_inspect_resolutions"] = lambda *_args, **_kwargs: (
        audit["Resolution"](
            "libxcb-cursor.so.0",
            str((runtime / "_internal/libxcb-cursor.so.0").resolve()),
            "bundled",
        ),
        audit["Resolution"](
            "libcups.so.2",
            str((runtime / "_internal/libcups.so.2").resolve()),
            "bundled",
        ),
        audit["Resolution"]("libEGL.so.1", "/system/libEGL.so.1", "host"),
        # ldd includes this transitive dependency, but the current ELF does
        # not have a direct DT_NEEDED edge to it.
        audit["Resolution"]("libz.so.1", "/system/libz.so.1", "host"),
    )

    report = audit["audit_runtime"](runtime)

    assert report.host_paths == (("libEGL.so.1", "/system/libEGL.so.1"),)
    assert report.host_sonames == ("libEGL.so.1",)


def test_debian_dependencies_are_direct_deduplicated_host_owners() -> None:
    audit = _load_runtime_audit()
    report = audit["RuntimeReport"](
        runtime="/opt/hesiva",
        elf_files=(),
        bundled_sonames=(),
        host_sonames=("libc.so.6", "libEGL.so.1"),
        host_paths=(
            ("libEGL.so.1", "/usr/lib/libEGL.so.1"),
            ("libc.so.6", "/usr/lib/libc.so.6"),
        ),
    )
    owners = {
        "/usr/lib/libEGL.so.1": "libegl1",
        "/usr/lib/libc.so.6": "libc6",
    }
    audit["debian_dependencies"].__globals__["_installed_debian_owner"] = owners.__getitem__
    audit["debian_dependencies"].__globals__["shutil"].which = lambda _command: "/usr/bin/tool"

    assert audit["debian_dependencies"](report) == ("libc6", "libegl1")


def test_installed_dependency_report_does_not_embed_build_root(tmp_path: Path) -> None:
    audit = _load_runtime_audit()
    build_root = tmp_path / "private-developer-path" / "Hesiva"
    report = audit["RuntimeReport"](
        runtime=str(build_root),
        elf_files=(
            audit["ElfRecord"](
                path="Hesiva",
                needed=("libexample.so.1",),
                rpath=(),
                runpath=("$ORIGIN/_internal",),
                resolutions=(
                    audit["Resolution"](
                        "libexample.so.1",
                        str(build_root / "_internal/libexample.so.1"),
                        "bundled",
                    ),
                ),
            ),
        ),
        bundled_sonames=("libexample.so.1",),
        host_sonames=(),
        host_paths=(),
    )

    output = audit["_text_report"](report)

    assert "runtime root: Hesiva (PyInstaller onedir)" in output
    assert "<runtime>/_internal/libexample.so.1" in output
    assert str(tmp_path) not in output
