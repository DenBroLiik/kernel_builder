#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then echo "Использование: bash tools/package-stone.sh каталог-успешной-сборки"; exit 0; fi
out=$(cd -- "${1:?Укажите каталог успешной сборки}" && pwd)
[[ -f "$out/BUILD-OK" && -f "$out/BUILD-INFO.txt" && -f "$out/SHA256SUMS" ]] || { echo "Сначала успешно выполните tools/build-stone.sh." >&2; exit 1; }
(cd -- "$out" && sha256sum -c SHA256SUMS)
[[ "$(cat "$out/SOURCE-ID")" == "$(bash "$root/tools/kernel-source-id.sh")" ]] || {
    echo 'Исходники ядра изменились после сборки. Сначала пересоберите ядро.' >&2
    exit 1
}
bash "$root/tools/check-feature-config.sh" "$out/.config"
magic=$(od -An -tx1 -j56 -N4 "$out/arch/arm64/boot/Image" | tr -d ' \n')
[[ "$magic" == 41524d64 ]] || { echo "Файл не является ARM64 Linux Image." >&2; exit 1; }
mkdir -p "$root/artifacts"
stage=$(mktemp -d "$root/validation/package.XXXXXXXX")
tar -C "$root/AnyKernel3" --exclude=.git --exclude=.github --exclude='*.zip' -cf - . | tar -C "$stage" -xf -
for file in Image dtb.img dtbo.img; do [[ -s "$out/arch/arm64/boot/$file" ]]; done
cp "$out/arch/arm64/boot/Image" "$stage/Image"
cp "$out/arch/arm64/boot/dtb.img" "$stage/dtb"
cp "$out/arch/arm64/boot/dtbo.img" "$stage/dtbo.img"
cp "$out/.config" "$stage/kernel.config"
cp "$out/BUILD-INFO.txt" "$stage/BUILD-INFO.txt"

cp "$out/SOURCE-ID" "$stage/SOURCE-ID"
sed -i 's/^kernel.string=.*/kernel.string=Eclipse Daily EXPERIMENTAL stone/' "$stage/anykernel.sh"
grep -qx 'do.devicecheck=1' "$stage/anykernel.sh"
grep -qx 'do.modules=0' "$stage/anykernel.sh"
variant=NoKSU
if grep -qx 'CONFIG_KSU=y' "$out/.config"; then variant=KSU; fi
archive="$root/artifacts/Eclipse-Daily-EXPERIMENTAL-$variant-stone-$(date -u +%Y%m%dT%H%M%SZ).zip"
(
    cd -- "$stage"
    sha256sum Image dtb dtbo.img kernel.config SOURCE-ID > SHA256SUMS
    zip -qr "$archive" . -x '*.git*' 'README*'
)
unzip -t "$archive"
(cd -- "$(dirname -- "$archive")" && sha256sum "$(basename -- "$archive")" > "$(basename -- "$archive").sha256")
echo "Экспериментальный ZIP: $archive"
echo "Только семейство stone и версии Android, разрешённые установщиком. Загрузка на телефоне не проверена."
