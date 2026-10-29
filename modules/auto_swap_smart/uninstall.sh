#!/system/bin/sh
# Do not swapoff live memory or erase user-created files on uninstall.
# The 2GiB swapfile stays on disk but will not be auto-activated after reboot.
exit 0
