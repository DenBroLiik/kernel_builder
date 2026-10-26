#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config=${1:-"$root/validation/stone-daily/.config"}
mkdir -p "$root/validation"
test_dir=$(mktemp -d "$root/validation/tool-tests.XXXXXXXX")
for script in "$root"/tools/*.sh "$root/build.sh"; do bash -n "$script"; done
printf '5\n0\n' | bash "$root/build.sh" --menu > "$test_dir/menu-help.log"
grep -q 'Повседневная конфигурация' "$test_dir/menu-help.log"
printf '' | bash "$root/build.sh" --menu > "$test_dir/menu-eof.log"
source_c=$(LC_ALL=C bash "$root/tools/kernel-source-id.sh")
source_ru=$(LC_ALL=ru_RU.UTF-8 bash "$root/tools/kernel-source-id.sh")
[[ "$source_c" == "$source_ru" ]]
echo "PASS: source identity is independent of terminal locale"
bash "$root/tools/check-feature-config.sh" "$config"
sed 's/^CONFIG_THERMAL=y$/# CONFIG_THERMAL is not set/' "$config" > "$test_dir/unsafe.config"
if bash "$root/tools/check-feature-config.sh" "$test_dir/unsafe.config" >/dev/null 2>&1; then
    echo "FAIL: missing thermal protection accepted" >&2; exit 1
fi
cp "$config" "$test_dir/unsafe.config"
echo CONFIG_USB_DUMMY_HCD=y >> "$test_dir/unsafe.config"
if bash "$root/tools/check-feature-config.sh" "$test_dir/unsafe.config" >/dev/null 2>&1; then
    echo "FAIL: USB test controller accepted" >&2; exit 1
fi
echo "PASS: configuration gates reject missing thermal protection and USB test controller"
cp "$config" "$test_dir/root-without-hooks.config"
"$root/kernel/scripts/config" --file "$test_dir/root-without-hooks.config" --enable KSU --disable KSU_HACK_ARM64_BRANCH_LINK --disable KSU_TAMPER_SYSCALL_TABLE --disable KSU_KPROBES_KSUD
if bash "$root/tools/check-feature-config.sh" "$test_dir/root-without-hooks.config" > "$test_dir/root-without-hooks.log" 2>&1; then
    echo 'FAIL: KernelSU without hooks accepted' >&2; exit 1
fi
grep -q 'KernelSU включён без механизма хуков' "$test_dir/root-without-hooks.log"
"$root/kernel/scripts/config" --file "$test_dir/root-without-hooks.config" --disable KSU
bash "$root/tools/check-feature-config.sh" "$test_dir/root-without-hooks.config" >/dev/null
echo 'PASS: rootless KernelSU configuration is rejected; intentionally disabled KernelSU is allowed'
for symbol in USB_CONFIGFS_F_HID MAC80211 CIFS ZRAM_MEMORY_TRACKING; do
    cp "$config" "$test_dir/experimental.config"
    "$root/kernel/scripts/config" --file "$test_dir/experimental.config" --enable "$symbol"
    if bash "$root/tools/check-feature-config.sh" "$test_dir/experimental.config" >/dev/null 2>&1; then
        echo "FAIL: removed feature $symbol accepted" >&2; exit 1
    fi
done
echo 'PASS: daily profile rejects removed experimental features and zram tracking'
