#!/system/bin/sh
MODDIR=${0%/*}
printf '\nAuto Swap 2GiB Smart v2.1 — status\n\n'
printf 'Active swap:\n'
cat /proc/swaps
printf '\nMemory:\n'
free -h 2>/dev/null || free
printf '\nZRAM compression (system values are never modified):\n'
for path in /sys/block/zram*/comp_algorithm; do
    [ -r "$path" ] || continue
    printf '%s: ' "${path%/comp_algorithm}"
    cat "$path"
done
printf '\nLast 30 log lines:\n'
if [ -f "$MODDIR/swap.log" ]; then
    tail -n 30 "$MODDIR/swap.log"
else
    printf 'No log yet. Reboot to run the module.\n'
fi
