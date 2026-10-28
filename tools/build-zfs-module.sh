#!/usr/bin/env bash
# Host-only cross build. Never inserts modules or accesses a disk/device.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then
    echo 'Использование: bash tools/build-zfs-module.sh clang/bin каталог-ядра исходники-openzfs [каталог-модуля]'
    exit 0
fi
toolchain=$(cd -- "${1:?Укажите каталог Clang}" && pwd)
kernel_out=$(cd -- "${2:?Укажите сборку KERNEL_PROFILE=zfs}" && pwd)
zfs_source=$(cd -- "${3:?Укажите исходники OpenZFS 2.4.4}" && pwd)
out=${4:-"$root/validation/zfs-module"}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd -P)
case "$out/" in "$root/kernel/"*|"$kernel_out/"*|"$zfs_source/"*) echo 'Нужен отдельный каталог результата.' >&2; exit 1;; esac
[[ -f "$kernel_out/BUILD-OK" && -s "$kernel_out/Module.symvers" ]] || {
    echo 'Сначала полностью соберите KERNEL_PROFILE=zfs, включая modules и Module.symvers.' >&2; exit 1;
}
(cd -- "$kernel_out" && sha256sum -c SHA256SUMS)
source_id=$(bash "$root/tools/kernel-source-id.sh")
[[ $(cat "$kernel_out/SOURCE-ID") == "$source_id" ]] || { echo 'Ядро не соответствует текущим исходникам.' >&2; exit 1; }
for symbol in MODULES MODVERSIONS; do
    grep -qx "CONFIG_$symbol=y" "$kernel_out/.config" || { echo "Нужен CONFIG_$symbol=y." >&2; exit 1; }
done
grep -qx 'CONFIG_LOCALVERSION="-Eclipse-ZFS-EXPERIMENTAL"' "$kernel_out/.config" || { echo 'Нужен отдельный профиль ZFS.' >&2; exit 1; }
pin=71a9f9578616a90c3c14bb59629fb4d31bfd68d1
namespace_patch="$root/patches/openzfs-2.4.4-stone-namespace.patch"
[[ $(git -C "$zfs_source" rev-parse HEAD) == "$pin" ]] || { echo 'Нужен точный upstream-коммит OpenZFS zfs-2.4.4.' >&2; exit 1; }
if git -C "$zfs_source" diff --quiet HEAD; then
    git -C "$zfs_source" apply --check "$namespace_patch"
    git -C "$zfs_source" apply "$namespace_patch"
fi
check_zfs_patch() {
    git -C "$zfs_source" --no-pager diff --no-color --no-ext-diff --no-textconv --binary HEAD | cmp -s "$namespace_patch" -
}
check_zfs_patch || { echo 'Исходники OpenZFS содержат изменения помимо известного патча namespace.' >&2; exit 1; }
[[ -x "$zfs_source/configure" ]] || { echo 'В исходниках OpenZFS сначала выполните AUTOPOINT=true sh autogen.sh.' >&2; exit 1; }
export PATH="$toolchain:$PATH"
export LLVM_IAS=1 CLANG_TRIPLE=aarch64-linux-gnu-
export KERNEL_CC=clang KERNEL_LD=ld.lld KERNEL_LLVM=1 KERNEL_ARCH=arm64 KERNEL_CROSS_COMPILE=aarch64-linux-gnu-
export TEST_JOBS=${JOBS:-4}
rm -f "$out/MODULE-BUILD-OK"
cd -- "$out"
"$zfs_source/configure" --host=aarch64-linux-gnu --target=aarch64-linux-gnu \
    --with-config=kernel --with-linux="$root/kernel" --with-linux-obj="$kernel_out" \
    --disable-pyzfs --with-python=no --disable-nls 2>&1 | tee configure.log
make gitrev
make -C module -j"${JOBS:-4}" 2>&1 | tee build.log
[[ $(bash "$root/tools/kernel-source-id.sh") == "$source_id" ]] || { echo 'Исходники ядра изменились во время сборки.' >&2; exit 1; }
[[ $(git -C "$zfs_source" rev-parse HEAD) == "$pin" ]] && check_zfs_patch || exit 1
for module in module/spl.ko module/zfs.ko; do
    [[ -s $module ]] || { echo "Отсутствует $module" >&2; exit 1; }
    "$toolchain/llvm-readelf" -h "$module" | grep -q 'Machine:.*AArch64'
done
cp "$kernel_out/SOURCE-ID" KERNEL-SOURCE-ID
cp "$kernel_out/Module.symvers" KERNEL-Module.symvers
printf '%s\n' "$pin" > OPENZFS-COMMIT
cp "$namespace_patch" OPENZFS-PATCH
sha256sum module/spl.ko module/zfs.ko KERNEL-SOURCE-ID KERNEL-Module.symvers OPENZFS-COMMIT OPENZFS-PATCH > SHA256SUMS
touch MODULE-BUILD-OK
echo 'ARM64-модули собраны. Android-утилиты, загрузка и доступ к существующему пулу ещё требуют проверки. На телефон ничего не установлено.'
