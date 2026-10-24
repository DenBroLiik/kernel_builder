#!/system/bin/sh
# Use Android's power service; never write voltage/frequency/thermal sysfs nodes.
set -eu
STATE=/data/local/tmp/stone-power-original
fail() { echo "ERROR: $*" >&2; exit 1; }
usage() { echo "Usage: sh phone-power.sh status | battery | balanced | restore"; }
case ${1:-status} in --help|-h|help) usage; exit 0;; esac
command -v getprop >/dev/null 2>&1 || fail "Run on the phone."
case $(getprop ro.product.device) in stone|moonstone|sunstone) ;; *) fail "Wrong device family.";; esac
if [ "${1:-status}" = status ]; then
    echo "Android battery saver: $(settings get global low_power)"
    exit 0
fi
[ "$(id -u)" = 0 ] || fail "Root is required."
case "$1" in battery) mode=1;; balanced) mode=0;; restore) mode=restore;; *) usage; exit 2;; esac
umask 077
if [ "$mode" = restore ]; then
    [ -f "$STATE" ] && [ ! -L "$STATE" ] || fail "No saved profile."
    mode=$(cat "$STATE")
    case "$mode" in 0|1) ;; *) fail "Invalid saved profile.";; esac
else
    if [ ! -e "$STATE" ]; then
        original=$(settings get global low_power)
        case "$original" in 0|1) ;; *) fail "Cannot read original power mode.";; esac
        (set -C; printf '%s\n' "$original" > "$STATE") || fail "Cannot save original mode."
    fi
    [ -f "$STATE" ] && [ ! -L "$STATE" ] || fail "Invalid state path."
fi
cmd power set-mode "$mode"
[ "$(settings get global low_power)" = "$mode" ] || fail "Android did not apply the requested mode (charging/policy may block it)."
if [ "$1" = restore ]; then rm "$STATE"; fi
echo "Android battery saver set to $mode; CPU/GPU limits and thermal protection remain under Android control."
