#!/usr/bin/env bash
# Stage a Linux/musl ARM64 userspace on the host, never on the phone.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then
    echo 'Использование: bash tools/prepare-zfs-userspace.sh apk.static каталог-ключей-Alpine [каталог-результата]'
    exit 0
fi
apk=$(realpath -- "${1:?Укажите apk-tools 3 static для хоста}")
keys=$(cd -- "${2:?Укажите доверенные публичные ключи Alpine}" && pwd)
out=${3:-"$root/validation/zfs-arm64-runtime"}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd -P)
case "$out/" in "$root/kernel/"*) echo 'Нужен отдельный каталог результата.' >&2; exit 1;; esac
[[ $out != / && $out != "$root" ]] || exit 1
[[ -x $apk ]] || { echo 'apk.static не исполняемый.' >&2; exit 1; }
rm -f "$out/USERSPACE-STAGED"
repo_file=$(mktemp "$root/validation/zfs-repositories.XXXXXXXX")
trap 'rm -f -- "$repo_file"' EXIT
echo 'https://dl-cdn.alpinelinux.org/alpine/edge/main' > "$repo_file"
"$apk" --usermode --root "$out" --arch aarch64 --keys-dir "$keys" \
    --repositories-file "$repo_file" --initdb --no-scripts add 'zfs=2.4.4-r0'
# No --allow-untrusted, package scripts, chroot, pool import or module loading.
"$apk" --root "$out" --arch aarch64 list --installed > "$out/PACKAGES.txt"
[[ -s "$out/usr/sbin/zpool" && -s "$out/usr/sbin/zfs" && -s "$out/lib/ld-musl-aarch64.so.1" ]]
printf '%s\n' 'OpenZFS 2.4.4; Alpine edge/main aarch64; Linux/musl runtime, not Android/bionic.' > "$out/USERSPACE-STAGED"
(
    cd -- "$out"
    rg --files --hidden --no-ignore -g '!SHA256SUMS' -0 | sort -z | xargs -0 -r sha256sum -- > SHA256SUMS
)
echo 'ARM64-утилиты подготовлены локально. На Android нужны root, изолированное Linux-окружение и совместимый модуль; это ещё не проверено.'
