# Preserve user configuration and managed-zram identity on in-place updates.
[ "$KSU" = true ] || abort 'KernelSU is required'
[ -x /data/adb/ksu/bin/busybox ] || abort 'KernelSU BusyBox is required'
[ -x /system/bin/swapon ] || abort 'Android swapon is required'
OLDMOD=/data/adb/modules/auto_swap_4gb
for name in config.conf zram.state; do
    if [ -f "$OLDMOD/$name" ] && [ ! -L "$OLDMOD/$name" ]; then
        cp "$OLDMOD/$name" "$MODPATH/$name" || abort 'Cannot preserve existing configuration'
    fi
done
set_perm_recursive "$MODPATH" 0 0 0755 0644
for name in service.sh action.sh uninstall.sh; do set_perm "$MODPATH/$name" 0 0 0755; done
ui_print 'Smart Swap 2GiB v2.1: existing Android zram is preserved.'
ui_print 'New settings take effect after reboot. Live swap is not disabled.'
