#!/bin/bash
# Fork 的 app 圖示（F1.6，design §F1）：從 1024×1024 的 PNG 產生 AppIcon.icns。
# 上游的 scripts/make-icon.swift 畫的是舊的波形圖示，fork 不用它。
# 用法：scripts/make-icon-from-png.sh [來源.png] [輸出.icns]
#   預設 Resources/AppIcon-1024.png → Resources/AppIcon.icns
# 換圖示時也要更新 docs/images/icon.png（256）和 site/public 的 favicon、apple-touch-icon（site/make-images.sh 的做法）。
set -euo pipefail
cd "$(dirname "$0")/.."
src="${1:-Resources/AppIcon-1024.png}"
out="${2:-Resources/AppIcon.icns}"

w=$(sips -g pixelWidth "$src" | awk '/pixelWidth/ {print $2}')
h=$(sips -g pixelHeight "$src" | awk '/pixelHeight/ {print $2}')
if [ "$w" != 1024 ] || [ "$h" != 1024 ]; then
  echo "$src 是 ${w}×${h}，要 1024×1024" >&2
  exit 1
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
set="$work/AppIcon.iconset"
mkdir "$set"
# sips 的縮圖是高品質的重新取樣（Lanczos 類）；每個尺寸都從 1024 原圖直接縮
for size in 16 32 128 256 512; do
  sips -z "$size" "$size" "$src" --out "$set/icon_${size}x${size}.png" >/dev/null
  double=$((size * 2))
  if [ "$double" = 1024 ]; then
    cp "$src" "$set/icon_${size}x${size}@2x.png"
  else
    sips -z "$double" "$double" "$src" --out "$set/icon_${size}x${size}@2x.png" >/dev/null
  fi
done
/usr/bin/iconutil -c icns "$set" -o "$out"
echo "已產生 ${out}（$(ls "$set" | wc -l | tr -d ' ') 張）"
