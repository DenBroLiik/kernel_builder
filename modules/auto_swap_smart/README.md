# Auto Swap 2GiB Smart v2.1.0

Updated from the user-supplied KernelSU ZIP v2.0.0. The original is preserved.
Original archive SHA256:
`6727ce302be4e25f158ff53adfd565303c5676ae4a1b454b958946768279aca0`.

The module ID remains `auto_swap_4gb` for an in-place upgrade. This is a 2 GiB
module, independent of the cancelled 512 MiB experiment. See README_RU.md for
installation and operating details in Russian.

Changes:

- Explicit Android `/system/bin/swapon` instead of the KernelSU BusyBox applet,
  whose inspected build lacks `-p` support.
- Nonnegative explicit file priority (0) below positive-priority zram; use
  kernel-assigned priority when zram is nonpositive. Verify activation and
  file priority against `/proc/swaps`; do not pass negative values to `-p`.
- Kernel `flock` instead of racy directory/PID locking.
- Preserve inactive 4 GiB legacy swap until a new 2 GiB file activates; restore
  it on activation failure. Never swapoff a live file or Android-owned zram.
- Root-only staging, size/header validation, fsync on the DD fallback, and
  no overwrite of unknown staging files.
- Abort when Android boot completion times out instead of racing system zram.
- Preserve user configuration and managed-zram state during upgrades.

Modes remain `auto`, `file`, and `zram`. Existing compressors, Android VM
settings and system-managed zram are not reconfigured. No resident daemon,
periodic swapoff, aggressive reclaim, or discard-on-activation is added.

Host checks from the builder root:

```
python3 tests/test-smart-swap.py
python3 tools/package-smart-swap.py
```

The test executes the actual service script in a sandbox. Swap commands and
sysfs are simulated; fake block nodes use regular files only in the test.
Host swap and phone state are never changed. Hardware activation and a reboot
remain untested for v2.1. No performance or battery benefit is claimed.

Install the resulting ZIP through KernelSU as an update. Existing active
legacy swap is deliberately left unchanged until reboot. Uninstall retains
live memory and its files; after reboot the module no longer activates them.
Never delete any file while it appears in `/proc/swaps`.

KernelSU boot/module reference: https://kernelsu.org/guide/module.html
