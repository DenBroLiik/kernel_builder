# OrangeFox: moonstone adaptation prototype

**DEVICE BOOT FAILED. DO NOT FLASH THIS PROTOTYPE.** On 2026-10-28 the user
reported a splash hang after flashing the candidate to boot_a, then restored
the original boot_a. Android boot completion was subsequently observed by ADB.
The cause is not established. Image generation is now disabled in the CLI,
and the failed local artifact has been renamed to `.img.disabled`.
The archive tests below validate host tooling only; they did not predict
successful device boot. A new source-based port/diagnosis is required before
another device attempt; replacing the boot ramdisk is not sufficient evidence
of Android 17 compatibility. Nothing here is a working recovery release.

The user identified the failure as the POCO/MI splash, before any OrangeFox
UI was observed. A subsequently supplied maintainer ZIP (SHA256
ee80b52ddcbc463ec3326ada35b530b64e27518cee275e5bbe9e3731fae829c0) contains
the same byte-identical donor recovery.img already used by the prototype.
It is not a different recovery build. The unchanged donor has its own kernel,
boot-v3 header, twrpfastboot=1 cmdline, a full 128 MiB partition image and
an AVB footer; avbtool verifies its self-contained SHA256 descriptor with
Algorithm NONE. This is structural integrity, not signature-based author
authentication or proof of compatibility with the current ROM.
The failed repack preserved the running kernel instead and omitted the AVB
footer. That is a material format difference, not an established root cause.
The running kernel's extracted config supports both gzip and LZ4 ramdisks.
The user has not tested the unchanged donor on the current Android 17;
reports from other users are not treated as a successful test on this phone.
No new recovery image was flashed during this comparison. The failed
prototype remains disabled; the original donor is retained separately for
a controlled baseline test with the existing original-boot rollback.

**The unchanged donor was subsequently tested too and the user reported a
boot loop.** The original boot_a was restored again; Android boot completion
and slot _a were then confirmed by ADB. With authorized root access, pstore
was empty, /proc/last_kmsg was absent and recovery log directories had no
saved log. There is no failure trace establishing a cause. Exact recovery
versus normal-system boot mode for this test has not yet been confirmed.
The extracted original image is now marked `.img.disabled` locally as well;
the user-supplied ZIP remains untouched. No repeated flash attempts or
working-compatibility claims should be based on this donor. Neither its
AVB-footer differences nor Android decryption are established as the cause.

Historical prototype description:

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
