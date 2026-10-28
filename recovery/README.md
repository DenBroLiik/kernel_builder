# OrangeFox: moonstone adaptation prototype

This is a host-only ramdisk adaptation tool, not a recovery source build or
an installer. It never invokes adb, fastboot, writes a phone partition or
modifies the donor images. No flashable ZIP is produced.

Verified on the connected POCO X5 5G during development: A/B boot partitions,
boot header v3, no separate recovery partition, vendor_boot v3 with a small
2557-byte vendor ramdisk and DTB. The current boot ramdisk carries recovery.
Do not infer layout for another ROM or device from these observations.

`tools/prepare-orangefox.py` accepts a fresh full-partition boot backup, its
expected SHA256, the pinned local OrangeFox R11.1_2 beta donor, and the current
vendor fstab. It preserves the current boot kernel, command line, OS version
and patch date; replaces the recovery ramdisk; and synchronizes only its
/data fstab entry with the existing F2FS/encryption options. Other ramdisk
entries, permissions and symlink payloads are preserved. Kernel/ramdisk
round-trip, image bounds, checksums and generated boot header are checked.

The old 2025 donor is NOT claimed to support Android 17 decryption. Its
crypto services, properties, touch behavior and ordinary Android boot still
require actual device testing. This approach is a binary ramdisk adaptation,
not a rebuild of modern OrangeFox or proof of full ROM compatibility.

The output is named `OrangeFox-moonstone-UNTESTED-boot.img` and is for review.
Original AVB signatures/footer are not copied or forged. Bootloader state
must be verified directly: Android properties reported locked/green while
the read-only kernel command line reported orange, so those properties
alone are not authoritative. No unlocking, AVB disabling or reboot occurs.

```sh
python3 tools/prepare-orangefox.py --help
python3 tests/test-orangefox.py
```

Input image checksum mismatches and ambiguous /data entries are rejected.
Current images and diagnostic data belong in ignored validation/artifacts,
not in Git. Preserve checksummed copies of both boot slots, both vendor_boot
and DTBO slots before proceeding. The legacy donor ZIP installer writes BOTH
boot slots; it is not used by this tool and must not be mistaken for the
single-image prototype. A future installation/recovery test needs a reviewed
rollback path and an agreed reboot window; no deployment is implemented here.

References:
- https://wiki.orangefox.tech/dev/building
- https://wiki.orangefox.tech/guides/installing_orangefox
