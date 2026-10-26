#!/usr/bin/env bash
# Non-interactive build; retains logs/output and never flashes a device.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if [[ ${1:-} == --help ]]; then
    echo "Использование: bash tools/build-stone.sh /путь/к/clang/bin [каталог-результата]"
    exit 0
fi
toolchain=${1:?Укажите каталог с clang, ld.lld и LLVM-инструментами}
toolchain=$(cd -- "$toolchain" && pwd)
out=${2:-"$root/validation/stone-daily"}
mkdir -p -- "$out"
out=$(cd -- "$out" && pwd -P)
case "$out/" in "$root/kernel/"*) echo "Каталог результата должен находиться вне дерева исходников kernel/." >&2; exit 1;; esac
for tool in clang ld.lld llvm-ar llvm-nm llvm-objcopy llvm-objdump llvm-strip; do
    [[ -x "$toolchain/$tool" ]] || { echo "Отсутствует $toolchain/$tool" >&2; exit 1; }
done
rm -f "$out/BUILD-OK"
source_id=$(bash "$root/tools/kernel-source-id.sh")
run_logs="$out/logs/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$run_logs"
export PATH="$toolchain:$PATH"
export KBUILD_BUILD_USER=stone-builder KBUILD_BUILD_HOST=local
export KBUILD_COMPILER_STRING
KBUILD_COMPILER_STRING=$(clang --version | head -n 1)
args=( -C "$root/kernel" "O=$out" ARCH=arm64 CC=clang HOSTCC=gcc LD=ld.lld
    AR=llvm-ar NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip
    CLANG_TRIPLE=aarch64-linux-gnu- CROSS_COMPILE=aarch64-linux-gnu-
    CROSS_COMPILE_ARM32=arm-linux-gnueabi- LLVM=1 LLVM_IAS=1 )
make "${args[@]}" stone_defconfig 2>&1 | tee "$out/configure.log" "$run_logs/configure.log"
case ${KSU_MODE:-keep} in
    keep) ;;
    y) "$root/kernel/scripts/config" --file "$out/.config" --enable KSU;;
    n) "$root/kernel/scripts/config" --file "$out/.config" --disable KSU;;
    *) echo "KSU_MODE должен быть keep, y или n." >&2; exit 2;;
esac
make "${args[@]}" olddefconfig 2>&1 | tee -a "$out/configure.log" "$run_logs/configure.log"
bash "$root/tools/check-feature-config.sh" "$out/.config"
if [[ ${CONFIG_ONLY:-0} == 1 ]]; then
    echo "Конфигурация проверена: $out/.config. Компиляция и упаковка не запускались."
    exit 0
fi
make "${args[@]}" -j"${JOBS:-8}" Image dtbs dtb.img dtbo.img 2>&1 | tee "$out/build.log" "$run_logs/build.log"
for file in Image dtb.img dtbo.img; do
    [[ -s "$out/arch/arm64/boot/$file" ]] || { echo "Отсутствует результат сборки $file" >&2; exit 1; }
done
file "$out/arch/arm64/boot/Image"
bash "$root/tools/check-feature-config.sh" "$out/.config"
[[ "$source_id" == "$(bash "$root/tools/kernel-source-id.sh")" ]] || {
    echo 'Исходники изменились во время сборки. Результат не помечен как успешный; повторите сборку.' >&2
    exit 1
}
printf '%s\n' "$source_id" > "$out/SOURCE-ID"
(
    cd -- "$out"
    sha256sum arch/arm64/boot/Image arch/arm64/boot/dtb.img arch/arm64/boot/dtbo.img .config SOURCE-ID > SHA256SUMS
    {
        date -u
        clang --version
        git -C "$root/kernel" rev-parse HEAD
        echo "Экспериментальная сборка семейства stone. Загрузка на устройстве не проверена."
    } > BUILD-INFO.txt
)
touch "$out/BUILD-OK"
echo "Сборка проверена: $out. Разделы телефона не изменялись."
