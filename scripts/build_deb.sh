#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

stage_only=false
stage_root=""
if [[ "${1:-}" == "--stage-only" ]]; then
    if [[ "$#" -ne 2 || "${2:-}" != /* || -e "${2:-}" ]]; then
        echo "Kullanım: scripts/build_deb.sh --stage-only /var/tmp/yeni-paket-kökü" >&2
        exit 2
    fi
    stage_only=true
    stage_root="$2"
elif [[ "$#" -ne 0 ]]; then
    echo "Kullanım: scripts/build_deb.sh [--stage-only /mutlak/yeni-paket-kökü]" >&2
    exit 2
fi

if [[ "$stage_only" == false ]] && ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "Debian paketi oluşturmak için dpkg-deb gereklidir; otomatik kurulum yapılmadı." >&2
    exit 1
fi
if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "Bu paket tarifi yalnız amd64/x86_64 build için tanımlıdır." >&2
    exit 1
fi

hesiva_python="${HESIVA_BUILD_PYTHON:-$repository_root/.venv/bin/python}"
if [[ ! -x "$hesiva_python" ]]; then
    echo "Build Python bulunamadı: $hesiva_python" >&2
    exit 1
fi

version="$($hesiva_python -c 'from hesiva.version import get_application_version; print(get_application_version())')"
if [[ ! "$version" =~ ^[0-9]+([.][0-9A-Za-z~+:-]+)*$ ]]; then
    echo "Debian paket sürümü geçersiz: $version" >&2
    exit 1
fi

runtime_source="$repository_root/dist/Hesiva"
if [[ ! -x "$runtime_source/Hesiva" ]]; then
    "$repository_root/scripts/build_linux.sh" --build-only
fi

if [[ "$stage_only" == true ]]; then
    package_root="$stage_root"
    mkdir -m 700 "$package_root"
else
    mkdir -p "$repository_root/build"
    package_root="$(mktemp -d "$repository_root/build/hesiva-deb-root.XXXXXX")"
    cleanup() {
        rm -rf -- "$package_root"
    }
    trap cleanup EXIT
fi

install -d -m 755 \
    "$package_root/DEBIAN" \
    "$package_root/opt/hesiva" \
    "$package_root/usr/bin" \
    "$package_root/usr/share/applications" \
    "$package_root/usr/share/doc/hesiva"
cp -a "$runtime_source/." "$package_root/opt/hesiva/"
install -m 755 packaging/linux/hesiva "$package_root/usr/bin/hesiva"
install -m 644 packaging/linux/hesiva.desktop \
    "$package_root/usr/share/applications/hesiva.desktop"
install -m 644 LICENSE "$package_root/usr/share/doc/hesiva/LICENSE"

for icon in packaging/icons/hicolor/*x*/apps/hesiva.png; do
    relative_path="${icon#packaging/icons/}"
    install -D -m 644 "$icon" "$package_root/usr/share/icons/$relative_path"
done

installed_size="$(du -sk "$package_root/opt" "$package_root/usr" | awk '{total += $1} END {print total}')"
sed \
    -e "s/@VERSION@/$version/g" \
    -e "s/@INSTALLED_SIZE@/$installed_size/g" \
    packaging/debian/control.in >"$package_root/DEBIAN/control"
chmod 644 "$package_root/DEBIAN/control"

if [[ "$stage_only" == true ]]; then
    echo "Debian package root staged for inspection: $package_root"
    exit 0
fi

artifact_path="$repository_root/dist/hesiva_${version}_amd64.deb"
dpkg-deb --root-owner-group --build "$package_root" "$artifact_path"
echo "Debian package artifact: $artifact_path"
