#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

hesiva_python="${HESIVA_BUILD_PYTHON:-$repository_root/.venv/bin/python}"
if [[ ! -x "$hesiva_python" ]]; then
    echo "Build Python bulunamadı: $hesiva_python" >&2
    exit 1
fi

build_only=false
if [[ "$#" -eq 1 && "$1" == "--build-only" ]]; then
    build_only=true
elif [[ "$#" -ne 0 ]]; then
    echo "Kullanım: scripts/build_linux.sh [--build-only]" >&2
    exit 2
fi

if [[ "$build_only" == false ]]; then
    "$hesiva_python" -m pytest
    "$hesiva_python" -m ruff check .
    "$hesiva_python" -m ruff format --check .
    git diff --check
fi

"$hesiva_python" packaging/license_inventory.py verify-policy

"$hesiva_python" packaging/artifact_provenance.py invalidate
source_digest="$("$hesiva_python" packaging/artifact_provenance.py source-digest)"
"$hesiva_python" -m PyInstaller --clean --noconfirm packaging/Hesiva.spec
"$hesiva_python" packaging/license_inventory.py stage-linux
"$hesiva_python" packaging/linux_runtime_audit.py verify
"$hesiva_python" packaging/license_inventory.py verify-runtime
"$hesiva_python" packaging/license_inventory.py verify-source-bundle \
    --release-directory "$repository_root/dist" \
    --runtime "$repository_root/dist/Hesiva"
"$hesiva_python" packaging/artifact_provenance.py record \
    --expected-source-sha256 "$source_digest"
"$hesiva_python" packaging/artifact_provenance.py verify

echo "Linux onedir artifact: $repository_root/dist/Hesiva"
