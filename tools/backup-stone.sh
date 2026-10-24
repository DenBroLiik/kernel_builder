#!/usr/bin/env bash
# Read phone partitions to this computer. Never writes a phone partition.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then echo "Использование: bash tools/backup-stone.sh ADB_SERIAL_POCO"; exit 0; fi
serial=${1:?Явно укажите ADB serial POCO; автоматический выбор телефона запрещён}
adb_cmd=(adb -s "$serial")
board=$("${adb_cmd[@]}" shell getprop ro.product.device | tr -d '\r')
case "$board" in stone|moonstone|sunstone) ;; *) echo "Отказ: устройство $board не относится к семейству stone." >&2; exit 1;; esac
uid=$("${adb_cmd[@]}" shell su -c 'id -u' | tr -d '\r')
[[ "$uid" == 0 ]] || { echo "Для чтения разделов требуется root." >&2; exit 1; }
dest="$root/artifacts/backups/$board-$(date -u +%Y%m%dT%H%M%SZ)"
umask 077
mkdir -p "$dest"
for prop in ro.product.device ro.product.model ro.build.fingerprint ro.boot.slot_suffix ro.boot.flash.locked; do
    printf '%s=' "$prop" >> "$dest/device.txt"
    "${adb_cmd[@]}" shell getprop "$prop" >> "$dest/device.txt"
done
for partition in boot_a boot_b dtbo_a dtbo_b vendor_boot_a vendor_boot_b init_boot_a init_boot_b; do
    exists=$("${adb_cmd[@]}" shell su -c "test -b /dev/block/by-name/$partition && echo yes" | tr -d '\r' || true)
    [[ "$exists" == yes ]] || continue
    expected=$("${adb_cmd[@]}" shell su -c "blockdev --getsize64 /dev/block/by-name/$partition" | tr -d '\r')
    [[ "$expected" =~ ^[1-9][0-9]*$ ]] || { echo "Не удалось определить размер $partition." >&2; exit 1; }
    "${adb_cmd[@]}" exec-out su -c "cat /dev/block/by-name/$partition" > "$dest/$partition.img.partial"
    actual=$(stat -c %s "$dest/$partition.img.partial")
    [[ "$actual" == "$expected" ]] || { echo "Неполная копия $partition: $actual/$expected байт." >&2; exit 1; }
    mv "$dest/$partition.img.partial" "$dest/$partition.img"
done
[[ -s "$dest/boot_a.img" && -s "$dest/boot_b.img" ]] || { echo "Необходимо сохранить оба boot-слота." >&2; exit 1; }
(cd -- "$dest" && sha256sum ./*.img > SHA256SUMS && sha256sum -c SHA256SUMS)
echo "Резервные копии разделов сохранены на компьютере: $dest"
echo "На телефон ничего не записывалось. Доступ к bootloader и процедуру восстановления нужно проверить отдельно."
