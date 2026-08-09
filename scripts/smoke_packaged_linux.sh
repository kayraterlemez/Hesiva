#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

hesiva_python="${HESIVA_BUILD_PYTHON:-$repository_root/.venv/bin/python}"
release_executable="$repository_root/dist/Hesiva/Hesiva"
if [[ ! -x "$hesiva_python" ]]; then
    echo "Build Python bulunamadı: $hesiva_python" >&2
    exit 1
fi
if [[ ! -x "$release_executable" ]]; then
    echo "Önce Linux onedir paketi oluşturulmalıdır: $release_executable" >&2
    exit 1
fi

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
        QT_QPA_PLATFORM=offscreen \
        timeout 3s "$release_executable" >"$smoke_root/launch.log" 2>&1
)
launch_status=$?
set -e
if [[ "$launch_status" -ne 124 ]]; then
    echo "Paketli uygulama ilk-kurulum ekranına ulaşamadı (durum: $launch_status)." >&2
    sed -n '1,80p' "$smoke_root/launch.log" >&2
    exit 1
fi
test -f "$smoke_root/launch-data/hesiva/hesiva.db"
test ! -e "$smoke_root/launch-data/hesiva/config.json"

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
        QT_QPA_PLATFORM=offscreen \
        "$repository_root/build/packaged-smoke-dist/HesivaRuntimeSmoke/HesivaRuntimeSmoke" \
        "$smoke_root/work"
)

after_digest="$(find dist/Hesiva -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum)"
if [[ "$before_digest" != "$after_digest" ]]; then
    echo "Paketli çalışma ağacı smoke sırasında değişti." >&2
    exit 1
fi
if find dist/Hesiva -type f \
    \( -name '*.db' -o -name 'config.json' -o -name '*.exa' -o -name 'Frm1.edb' \) \
    | grep -q .; then
    echo "Kullanıcı verisi yanlışlıkla dağıtım dizinine yazıldı." >&2
    exit 1
fi

echo "Packaged Linux smoke completed without modifying dist/Hesiva."
