#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

hesiva_python="${HESIVA_BUILD_PYTHON:-$repository_root/.venv/bin/python}"
if [[ ! -x "$hesiva_python" ]]; then
    echo "Build Python bulunamadı: $hesiva_python" >&2
    exit 1
fi

if [[ "${1:-}" != "--build-only" ]]; then
    "$hesiva_python" -m pytest
    "$hesiva_python" -m ruff check .
    "$hesiva_python" -m ruff format --check .
    git diff --check
fi

"$hesiva_python" -m PyInstaller --clean --noconfirm packaging/Hesiva.spec

echo "Linux onedir artifact: $repository_root/dist/Hesiva"
