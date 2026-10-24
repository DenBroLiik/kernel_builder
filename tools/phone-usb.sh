#!/system/bin/sh
# Add one temporary function to the existing gadget; preserve Android/ADB links.
set -eu
STATE=/data/local/tmp/stone-usb-state
LOCK=/data/local/tmp/stone-usb-lock
fail() { echo "ERROR: $*" >&2; exit 1; }
usage() {
    echo "Usage: sh phone-usb.sh status | enable keyboard|mouse|midi|iso [image.iso] | commit | restore"
    echo "enable disconnects USB briefly, preserves existing functions, and rolls back after 60s."
}
case ${1:-status} in help|--help|-h) usage; exit 0;; esac
command -v getprop >/dev/null 2>&1 || fail "Run this script on the phone."
case $(getprop ro.product.device) in stone|moonstone|sunstone) ;; *) fail "Only stone/moonstone/sunstone devices are allowed.";; esac
find_gadget() {
    gadget=
    for root in /config/usb_gadget /sys/kernel/config/usb_gadget; do
        [ -d "$root" ] || continue
        for candidate in "$root"/*; do
            [ -f "$candidate/UDC" ] || continue
            [ -n "$(cat "$candidate/UDC")" ] || continue
            real=$(readlink -f "$candidate")
            [ -z "$gadget" ] || [ "$gadget" = "$real" ] || fail "Multiple active gadgets."
            gadget=$real
        done
    done
    [ -n "$gadget" ] || fail "No active configfs gadget; let Android initialize USB first."
}
if [ "${1:-status}" = status ]; then
    find_gadget
    echo "Gadget: $gadget; UDC: $(cat "$gadget/UDC")"
    ls -l "$gadget"/configs/*/ 2>/dev/null || true
    [ ! -d "$STATE" ] || echo "Temporary function state exists: $STATE"
    exit 0
fi
[ "$(id -u)" = 0 ] || fail "Root is required."
umask 077
mkdir "$LOCK" 2>/dev/null || fail "Another USB operation is running."
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
restore_impl() {
    [ -d "$STATE" ] || return 0
    g=$(cat "$STATE/gadget")
    cfg=$(cat "$STATE/config")
    func=$(cat "$STATE/function")
    old_udc=$(cat "$STATE/udc")
    # Never evaluate saved text or remove an Android-owned link/function.
    case "$g" in /config/usb_gadget/*|/sys/kernel/config/usb_gadget/*) ;; *) return 1;; esac
    case "$cfg" in "$g"/configs/*) ;; *) return 1;; esac
    case "$func" in hid.stone_keyboard|hid.stone_mouse|midi.stone_tool|mass_storage.stone_tool) ;; *) return 1;; esac
    printf '\n' > "$g/UDC" || return 1
    if [ -L "$cfg/f_stone_tool" ]; then
        [ "$(readlink "$cfg/f_stone_tool")" = "$g/functions/$func" ] || return 1
        rm "$cfg/f_stone_tool" || return 1
    fi
    if [ -d "$g/functions/$func" ]; then
        case "$func" in mass_storage.*) printf '\n' > "$g/functions/$func/lun.0/file" || return 1;; esac
        rmdir "$g/functions/$func" || return 1
    fi
    printf '%s\n' "$old_udc" > "$g/UDC" || return 1
    rm -f "$STATE/gadget" "$STATE/config" "$STATE/function" "$STATE/udc" "$STATE/token" "$STATE/committed"
    rmdir "$STATE"
    echo "Original USB composition restored."
}
case ${1:-} in
    watchdog)
        [ -d "$STATE" ] || exit 0
        [ "$(cat "$STATE/token")" = "${2:-}" ] || exit 0
        [ ! -f "$STATE/committed" ] || exit 0
        restore_impl
        exit $?;;
    restore) restore_impl; exit $?;;
    commit)
        [ -d "$STATE" ] || fail "No temporary USB function."
        : > "$STATE/committed"
        echo "Rollback timer cancelled. Use restore to undo; reboot also resets this temporary setup."
        exit 0;;
    enable) ;;
    *) usage; exit 2;;
esac
[ ! -e "$STATE" ] || fail "Restore the previous temporary function first."
command -v nohup >/dev/null 2>&1 || fail "nohup is required for the rollback watchdog."
self=$(readlink -f "$0")
[ -f "$self" ] || fail "Save this script as a file on the phone first."
find_gadget
config=
for candidate in "$gadget"/configs/*; do
    [ -d "$candidate" ] || continue
    [ -z "$config" ] || fail "Multiple configurations; automatic modification is refused."
    config=$candidate
done
[ -n "$config" ] || fail "No USB configuration."
[ ! -e "$config/f_stone_tool" ] && [ ! -L "$config/f_stone_tool" ] || fail "Reserved link already exists."
case ${2:-} in
    keyboard) function=hid.stone_keyboard;;
    mouse) function=hid.stone_mouse;;
    midi) function=midi.stone_tool;;
    iso)
        image=${3:-}
        case "$image" in /*.iso|/*.ISO) ;; *) fail "Use an absolute path to a dedicated ISO file.";; esac
        [ -f "$image" ] && [ ! -b "$image" ] || fail "Only a regular ISO file is accepted."
        function=mass_storage.stone_tool;;
    *) usage; exit 2;;
esac
[ ! -e "$gadget/functions/$function" ] || fail "Reserved function already exists."
mkdir "$STATE"
printf '%s\n' "$gadget" > "$STATE/gadget"
printf '%s\n' "$config" > "$STATE/config"
printf '%s\n' "$function" > "$STATE/function"
cat "$gadget/UDC" > "$STATE/udc"
token="$(date +%s)-$$"
printf '%s\n' "$token" > "$STATE/token"
# The watchdog is detached before the USB controller is disconnected.
nohup sh -c 'sleep 60; exec sh "$1" watchdog "$2"' sh "$self" "$token" </dev/null >/dev/null 2>&1 &
on_failure() {
    code=$?
    trap - EXIT HUP INT TERM
    restore_impl || echo "Restore failed; reboot the phone to restore Android USB." >&2
    rmdir "$LOCK" 2>/dev/null || true
    exit "$code"
}
trap on_failure EXIT
trap 'exit 1' HUP INT TERM
printf '\n' > "$gadget/UDC"
mkdir "$gadget/functions/$function"
case "$function" in
    hid.stone_keyboard)
        echo 1 > "$gadget/functions/$function/protocol"
        echo 1 > "$gadget/functions/$function/subclass"
        echo 8 > "$gadget/functions/$function/report_length"
        printf '\005\001\011\006\241\001\005\007\031\340\051\347\025\000\045\001\165\001\225\010\201\002\225\001\165\010\201\001\225\005\165\001\005\010\031\001\051\005\221\002\225\001\165\003\221\001\225\006\165\010\025\000\045\145\005\007\031\000\051\145\201\000\300' > "$gadget/functions/$function/report_desc";;
    hid.stone_mouse)
        echo 2 > "$gadget/functions/$function/protocol"
        echo 1 > "$gadget/functions/$function/subclass"
        echo 4 > "$gadget/functions/$function/report_length"
        printf '\005\001\011\002\241\001\011\001\241\000\005\011\031\001\051\003\025\000\045\001\225\003\165\001\201\002\225\001\165\005\201\001\005\001\011\060\011\061\011\070\025\201\045\177\165\010\225\003\201\006\300\300' > "$gadget/functions/$function/report_desc";;
    mass_storage.stone_tool)
        echo 1 > "$gadget/functions/$function/lun.0/ro"
        echo 1 > "$gadget/functions/$function/lun.0/removable"
        echo 1 > "$gadget/functions/$function/lun.0/cdrom"
        printf '%s\n' "$image" > "$gadget/functions/$function/lun.0/file";;
esac
ln -s "$gadget/functions/$function" "$config/f_stone_tool"
cat "$STATE/udc" > "$gadget/UDC"
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
trap - HUP INT TERM
echo "Temporary $function enabled. Test USB, then run commit within 60 seconds or it will be restored."
echo "Android USB HAL may override this configuration. HID report input/MIDI software is separate."
