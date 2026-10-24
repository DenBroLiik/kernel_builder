#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config=${1:-"$root/validation/stone-android21/.config"}
mkdir -p "$root/validation"
test_dir=$(mktemp -d "$root/validation/tool-tests.XXXXXXXX")
mock="$test_dir/bin"
mkdir -p "$mock"
cat > "$mock/getprop" <<'EOF'
#!/bin/sh
echo "${TEST_BOARD:-pine}"
EOF
cat > "$mock/id" <<'EOF'
#!/bin/sh
echo 0
EOF
chmod +x "$mock/getprop" "$mock/id"
for script in "$root"/tools/*.sh; do bash -n "$script"; done
bash -n "$root/build.sh"
printf '5\n0\n' | bash "$root/build.sh" --menu > "$test_dir/menu-help.log"
grep -q 'Дополнительные возможности' "$test_dir/menu-help.log"
printf '' | bash "$root/build.sh" --menu > "$test_dir/menu-eof.log"
(
    source "$root/tools/features.sh"
    export FEATURE_USB_WIFI=0
    printf 'CONFIG_MT76x0U=y\nCONFIG_MT76x2U=y\n' > "$test_dir/mixed-case.config"
    feature_apply "$test_dir/mixed-case.config" "$root/kernel/scripts/config"
    grep -qx '# CONFIG_MT76x0U is not set' "$test_dir/mixed-case.config"
    grep -qx '# CONFIG_MT76x2U is not set' "$test_dir/mixed-case.config"
    printf 'FEATURE_USB_WIFI=$(touch SHOULD_NOT_EXIST)\n' > "$test_dir/bad-profile.env"
    if feature_load "$test_dir/bad-profile.env" >/dev/null 2>&1; then exit 1; fi
)
echo "PASS: Russian menu, clean EOF exit, mixed-case Kconfig flags, strict feature-profile parsing"
source_c=$(LC_ALL=C bash "$root/tools/kernel-source-id.sh")
source_ru=$(LC_ALL=ru_RU.UTF-8 bash "$root/tools/kernel-source-id.sh")
[[ "$source_c" == "$source_ru" ]]
echo "PASS: source identity is independent of terminal locale"
for name in phone-usb phone-netfs phone-power phone-report; do
    sh "$root/tools/$name.sh" --help >/dev/null
    if env PATH="$mock:$PATH" TEST_BOARD=pine sh "$root/tools/$name.sh" status > "$test_dir/$name-reject.log" 2>&1; then
        echo "FAIL: $name accepted an unsupported phone" >&2; exit 1
    fi
done
echo "PASS: wrong-device refusal and shell syntax"
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
# Test-only copy with paths redirected into a fake configfs. Production has no
# environment override that could bypass its device/path guards.
sed -e "s|/data/local/tmp|$test_dir/data|g" -e "s|/config/usb_gadget|$test_dir/config/usb_gadget|g" -e "s|/sys/kernel/config/usb_gadget|$test_dir/sys-usb|g" \
    "$root/tools/phone-usb.sh" > "$test_dir/phone-usb.sh"
g="$test_dir/config/usb_gadget/g1"
mkdir -p "$test_dir/data" "$g/configs/c.1" "$g/functions/ffs.adb"
printf 'test_udc\n' > "$g/UDC"
ln -s "$g/functions/ffs.adb" "$g/configs/c.1/f_adb"
cat > "$mock/nohup" <<'EOF'
#!/bin/sh
# Timer is triggered explicitly by the test, without a 60-second sleep.
exit 0
EOF
cat > "$mock/mkdir" <<'EOF'
#!/bin/sh
/usr/bin/mkdir "$@" || exit $?
case "$1" in */mass_storage.stone_tool) /usr/bin/mkdir "$1/lun.0";; esac
EOF
cat > "$mock/rmdir" <<'EOF'
#!/bin/sh
# Fake configfs attributes are ordinary files in this fixture only.
case "$1" in
    */functions/hid.stone_*|*/functions/midi.stone_tool)
        /usr/bin/rm -f "$1/protocol" "$1/subclass" "$1/report_length" "$1/report_desc";;
    */functions/mass_storage.stone_tool)
        /usr/bin/rm -f "$1/lun.0/file" "$1/lun.0/ro" "$1/lun.0/removable" "$1/lun.0/cdrom"
        /usr/bin/rmdir "$1/lun.0";;
esac
exec /usr/bin/rmdir "$@"
EOF
cat > "$mock/ln" <<'EOF'
#!/bin/sh
[ "${TEST_FAIL_LINK:-0}" != 1 ] || exit 1
if [ "${TEST_HUP_LINK:-0}" = 1 ]; then kill -HUP "$PPID"; exit 1; fi
exec /usr/bin/ln "$@"
EOF
chmod +x "$mock"/*
usb() { env PATH="$mock:$PATH" TEST_BOARD=stone TEST_FAIL_LINK="${TEST_FAIL_LINK:-0}" TEST_HUP_LINK="${TEST_HUP_LINK:-0}" sh "$test_dir/phone-usb.sh" "$@"; }
assert_restored() {
    [[ $(cat "$g/UDC") == test_udc ]]
    [[ $(readlink "$g/configs/c.1/f_adb") == "$g/functions/ffs.adb" ]]
    [[ ! -L "$g/configs/c.1/f_stone_tool" && ! -e "$test_dir/data/stone-usb-state" ]]
    [[ ! -e "$test_dir/data/stone-usb-lock" ]]
}
usb enable keyboard >/dev/null
[[ $(cat "$g/functions/hid.stone_keyboard/report_length") == 8 ]]
[[ -L "$g/configs/c.1/f_adb" ]]
token=$(cat "$test_dir/data/stone-usb-state/token")
usb watchdog "$token" >/dev/null
assert_restored
echo "PASS: keyboard enable and watchdog restoration preserve ADB"
usb enable mouse >/dev/null
[[ $(cat "$g/functions/hid.stone_mouse/report_length") == 4 ]]
token=$(cat "$test_dir/data/stone-usb-state/token")
usb commit >/dev/null
usb watchdog "$token" >/dev/null
[[ -L "$g/configs/c.1/f_stone_tool" ]]
usb restore >/dev/null
assert_restored
echo "PASS: commit prevents automatic rollback, manual restore still works"
printf 'test ISO\n' > "$test_dir/test.iso"
usb enable iso "$test_dir/test.iso" >/dev/null
[[ $(cat "$g/functions/mass_storage.stone_tool/lun.0/ro") == 1 ]]
[[ $(cat "$g/functions/mass_storage.stone_tool/lun.0/cdrom") == 1 ]]
usb restore >/dev/null
assert_restored
if usb enable iso /dev/null >/dev/null 2>&1; then echo "FAIL: non-ISO device accepted"; exit 1; fi
assert_restored
echo "PASS: ISO export is read-only and rejects device paths"
if TEST_FAIL_LINK=1 usb enable midi >/dev/null 2>&1; then echo "FAIL: injected link failure ignored"; exit 1; fi
assert_restored
echo "PASS: failed enable restores USB and removes temporary state"
if TEST_HUP_LINK=1 usb enable midi >/dev/null 2>&1; then echo "FAIL: disconnected session reported success"; exit 1; fi
assert_restored
echo "PASS: session hangup returns failure and restores the original USB composition"
sed "s|/data/local/tmp|$test_dir/data|g" "$root/tools/phone-power.sh" > "$test_dir/phone-power.sh"
cat > "$mock/settings" <<'EOF'
#!/bin/sh
cat "$TEST_POWER_FILE"
EOF
cat > "$mock/cmd" <<'EOF'
#!/bin/sh
[ "$1" = power ] && [ "$2" = set-mode ] || exit 1
[ "${TEST_BLOCK_POWER:-0}" != 1 ] || exit 0
printf '%s\n' "$3" > "$TEST_POWER_FILE"
EOF
chmod +x "$mock/settings" "$mock/cmd"
power() { env PATH="$mock:$PATH" TEST_BOARD=stone TEST_POWER_FILE="$test_dir/power-mode" TEST_BLOCK_POWER="${TEST_BLOCK_POWER:-0}" sh "$test_dir/phone-power.sh" "$@"; }
for original in 0 1; do
    echo "$original" > "$test_dir/power-mode"
    power battery >/dev/null
    [[ $(cat "$test_dir/power-mode") == 1 ]]
    power balanced >/dev/null
    [[ $(cat "$test_dir/power-mode") == 0 ]]
    power restore >/dev/null
    [[ $(cat "$test_dir/power-mode") == "$original" ]]
done
echo 0 > "$test_dir/power-mode"
if TEST_BLOCK_POWER=1 power battery >/dev/null 2>&1; then echo "FAIL: blocked power change reported success"; exit 1; fi
power restore >/dev/null
echo "PASS: power profiles restore the original mode and detect rejected changes"
echo "All host tests passed. Fake configfs tests do not prove Android HAL or hardware compatibility."
