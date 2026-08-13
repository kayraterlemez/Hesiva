#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

hesiva_python="${HESIVA_BUILD_PYTHON:-$repository_root/.venv/bin/python}"
release_executable="$repository_root/dist/Hesiva/Hesiva"
smoke_platform="${HESIVA_SMOKE_QPA_PLATFORM:-offscreen}"
case "$smoke_platform" in
    offscreen|xcb|wayland) ;;
    *)
        echo "Geçersiz Qt smoke platformu: $smoke_platform" >&2
        exit 2
        ;;
esac
if [[ ! -x "$hesiva_python" ]]; then
    echo "Build Python bulunamadı: $hesiva_python" >&2
    exit 1
fi
if [[ ! -x "$release_executable" ]]; then
    echo "Önce Linux onedir paketi oluşturulmalıdır: $release_executable" >&2
    exit 1
fi
"$hesiva_python" packaging/artifact_provenance.py verify
"$hesiva_python" packaging/linux_runtime_audit.py verify

smoke_root="$(mktemp -d /tmp/hesiva-packaged-smoke.XXXXXX)"
chmod 700 "$smoke_root"
cleanup() {
    rm -rf -- "$smoke_root"
}
trap cleanup EXIT

mkdir -m 700 "$smoke_root/home" "$smoke_root/cwd"
before_digest="$(find dist/Hesiva -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)"

set +e
(
    cd "$smoke_root/cwd"
        HOME="$smoke_root/home" \
        XDG_DATA_HOME="$smoke_root/launch-data" \
        QT_QPA_PLATFORM="$smoke_platform" \
        QT_LOGGING_RULES='qt.qpa.backingstore=true' \
        timeout 3s "$release_executable" >"$smoke_root/launch.log" 2>&1
)
launch_status=$?
set -e
if [[ "$launch_status" -ne 124 ]]; then
    echo "Paketli uygulama ilk-kurulum ekranına ulaşamadı (durum: $launch_status)." >&2
    sed -n '1,80p' "$smoke_root/launch.log" >&2
    exit 1
fi
if grep -Eq \
    'Hesiva startup failed|Hesiva authenticated startup failed|Unexpected error during|startup blocked' \
    "$smoke_root/launch.log"; then
    echo "Paketli uygulama ilk-kurulum yerine hata penceresine ulaştı." >&2
    sed -n '1,80p' "$smoke_root/launch.log" >&2
    exit 1
fi
if ! grep -q '^qt.qpa.backingstore:' "$smoke_root/launch.log"; then
    echo "Paketli uygulama ilk-kurulum penceresi için Qt yüzeyi oluşturmadı." >&2
    sed -n '1,80p' "$smoke_root/launch.log" >&2
    exit 1
fi
test -f "$smoke_root/launch-data/hesiva/hesiva.db"
test ! -e "$smoke_root/launch-data/hesiva/config.json"
"$hesiva_python" - "$smoke_root/launch-data/hesiva/hesiva.db" <<'PY'
import sqlite3
import sys
from pathlib import Path

from hesiva.database.startup import get_migration_head
from hesiva.models import model_metadata

database_path = Path(sys.argv[1]).resolve()
connection = sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
try:
    integrity_result = connection.execute("PRAGMA integrity_check").fetchone()
    actual_tables = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }
    migration_row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
finally:
    connection.close()

expected_tables = {*model_metadata.tables, "alembic_version"}
if integrity_result != ("ok",):
    raise SystemExit(f"Frozen application created an invalid SQLite database: {integrity_result}")
if actual_tables != expected_tables:
    raise SystemExit(
        f"Frozen application schema mismatch: expected {sorted(expected_tables)}, "
        f"found {sorted(actual_tables)}"
    )
if migration_row != (get_migration_head(),):
    raise SystemExit(
        f"Frozen application migration mismatch: expected {get_migration_head()}, "
        f"found {migration_row}"
    )
PY

"$hesiva_python" -m PyInstaller \
    --clean \
    --noconfirm \
    --distpath "$repository_root/build/packaged-smoke-dist" \
    --workpath "$repository_root/build/packaged-smoke-work" \
    packaging/HesivaRuntimeSmoke.spec

(
    cd "$smoke_root/cwd"
    HOME="$smoke_root/home" \
        XDG_DATA_HOME="$smoke_root/runtime-data" \
        QT_QPA_PLATFORM="$smoke_platform" \
        "$repository_root/build/packaged-smoke-dist/HesivaRuntimeSmoke/HesivaRuntimeSmoke" \
        "$smoke_root/work"
)

after_digest="$(find dist/Hesiva -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)"
if [[ "$before_digest" != "$after_digest" ]]; then
    echo "Paketli çalışma ağacı smoke sırasında değişti." >&2
    exit 1
fi
"$hesiva_python" packaging/artifact_provenance.py verify
if find dist/Hesiva -type f \
    \( -name '*.db' -o -name 'config.json' -o -name '*.exa' -o -name 'Frm1.edb' \) \
    | grep -q .; then
    echo "Kullanıcı verisi yanlışlıkla dağıtım dizinine yazıldı." >&2
    exit 1
fi

echo "Packaged Linux smoke ($smoke_platform) completed without modifying dist/Hesiva."
