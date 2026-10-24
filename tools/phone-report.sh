#!/system/bin/sh
# Read-only device diagnostics. No tuning, USB reconfiguration or flashing.
set -u
case ${1:-} in --help|-h|help) echo "Usage: sh phone-report.sh > report.txt (root adds access to kernel logs)"; exit 0;; esac
command -v getprop >/dev/null 2>&1 || { echo "Run on the phone." >&2; exit 1; }
case $(getprop ro.product.device) in stone|moonstone|sunstone) ;; *) echo "Wrong device family." >&2; exit 1;; esac
section() { printf '\n=== %s ===\n' "$1"; }
section identity
date
uname -a
for prop in ro.product.device ro.product.model ro.build.version.release ro.build.display.id ro.boot.slot_suffix ro.boot.flash.locked ro.boot.verifiedbootstate; do
    printf '%s=%s\n' "$prop" "$(getprop "$prop")"
done
section memory
cat /proc/meminfo /proc/swaps 2>/dev/null
for path in /proc/pressure/* /sys/block/zram*/mm_stat /sys/block/zram*/bd_stat /sys/block/zram*/comp_algorithm; do
    [ -r "$path" ] || continue
    echo "$path"; cat "$path"
done
section cpu
for path in /sys/devices/system/cpu/cpufreq/policy*/scaling_governor /sys/devices/system/cpu/cpufreq/policy*/scaling_min_freq /sys/devices/system/cpu/cpufreq/policy*/scaling_max_freq /sys/devices/system/cpu/vulnerabilities/*; do
    [ -r "$path" ] || continue
    echo "$path"; cat "$path"
done
section battery_thermal
dumpsys battery 2>/dev/null
dumpsys thermalservice 2>/dev/null
for path in /sys/class/power_supply/battery/current_now /sys/class/power_supply/battery/charge_counter /sys/class/power_supply/battery/temp /sys/class/thermal/thermal_zone*/temp /sys/class/thermal/thermal_zone*/type; do
    [ -r "$path" ] || continue
    echo "$path"; cat "$path"
done
section suspend
cat /sys/power/suspend_stats/* /sys/kernel/debug/wakeup_sources 2>/dev/null
section interfaces
ip link show 2>/dev/null
ls /sys/class/bluetooth /sys/class/tty /sys/class/udc 2>/dev/null
section usb
for path in /sys/bus/usb/devices/*/idVendor /sys/bus/usb/devices/*/idProduct /config/usb_gadget/*/UDC /sys/kernel/config/usb_gadget/*/UDC; do
    [ -r "$path" ] || continue
    echo "$path"; cat "$path"
done
section filesystems_containers
cat /proc/filesystems /proc/cgroups 2>/dev/null
ls /proc/self/ns 2>/dev/null
section pstore
for path in /sys/fs/pstore/*; do
    [ -f "$path" ] && [ -r "$path" ] || continue
    echo "$path"; cat "$path"
done
section kernel_log
dmesg 2>/dev/null | tail -n 250
exit 0
