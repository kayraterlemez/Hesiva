#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
master_icon="$repository_root/assets/hesiva-icon.png"
icon_root="$repository_root/packaging/icons"

if ! command -v magick >/dev/null 2>&1; then
    echo "ImageMagick 'magick' aracı bulunamadı; ikonlar üretilemedi." >&2
    exit 1
fi
if [[ ! -f "$master_icon" ]]; then
    echo "Ana Hesiva ikonu bulunamadı: $master_icon" >&2
    exit 1
fi

sizes=(16 32 48 64 128 256 512)
for size in "${sizes[@]}"; do
    destination_directory="$icon_root/hicolor/${size}x${size}/apps"
    mkdir -p "$destination_directory"
    magick "$master_icon" \
        -filter Lanczos \
        -resize "${size}x${size}" \
        -strip \
        -define png:color-type=6 \
        "PNG32:$destination_directory/hesiva.png"
done

magick "$master_icon" \
    -filter Lanczos \
    -define icon:auto-resize=256,128,64,48,32,24,16 \
    -strip \
    "$icon_root/hesiva.ico"

echo "Hesiva Linux PNG ve Windows ICO türevleri üretildi: $icon_root"
