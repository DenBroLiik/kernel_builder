#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Disabled legacy prototype: device boot hung. No flashing or adb operations."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess

BASE_FOX_SHA256 = "3f99cdd1c0d5437ba39ea1e177a3058b551a21e6771f4b6e25c28f0ead22b0b5"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def align(n, size=4):
    return (n + size - 1) // size * size


def boot_v3(data):
    if len(data) < 4096 or data[:8] != b"ANDROID!":
        raise ValueError("Not an Android boot image")
    kernel_size, ramdisk_size, os_version, header_size = struct.unpack_from("<4I", data, 8)
    if struct.unpack_from("<I", data, 40)[0] != 3 or header_size != 1580:
        raise ValueError("Only verified boot header v3 is supported")
    start = 4096 + align(kernel_size, 4096)
    if not kernel_size or not ramdisk_size or start + ramdisk_size > len(data):
        raise ValueError("Truncated/empty boot payload")
    cmdline = data[44:1580].split(b"\0", 1)[0].decode("ascii")
    return data[4096:4096 + kernel_size], data[start:start + ramdisk_size], os_version, cmdline


def cpio_entries(data):
    pos, result = 0, []
    while pos + 110 <= len(data):
        header = data[pos:pos + 110]
        if header[:6] != b"070701":
            raise ValueError("Only uncompressed newc archives are supported")
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        size, namesize = fields[6], fields[11]
        end_name = pos + 110 + namesize
        if not namesize or end_name > len(data) or data[end_name - 1] != 0:
            raise ValueError("Invalid cpio filename")
        name = data[pos + 110:end_name - 1].decode("utf-8")
        start = align(end_name)
        if start + size > len(data):
            raise ValueError("Truncated cpio entry")
        result.append((name, fields, data[start:start + size]))
        pos = align(start + size)
        if name == "TRAILER!!!":
            return result
    raise ValueError("Missing cpio trailer")


def encode_cpio(entries):
    out = bytearray()
    for name, fields, payload in entries:
        fields = list(fields)
        encoded = name.encode() + b"\0"
        fields[6], fields[11] = len(payload), len(encoded)
        out += b"070701" + b"".join(f"{v:08x}".encode() for v in fields)
        out += encoded
        out += b"\0" * (align(len(out)) - len(out))
        out += payload
        out += b"\0" * (align(len(out)) - len(out))
    out += b"\0" * (align(len(out), 512) - len(out))
    return bytes(out)


def adapt_fstab(old, current):
    def data_lines(text):
        return [line for line in text.splitlines() if not line.lstrip().startswith("#")
                and len(line.split()) >= 5 and line.split()[1] == "/data"]
    target = data_lines(current)
    if len(target) != 1 or len(data_lines(old)) != 1:
        raise ValueError("Expected exactly one /data entry in each fstab")
    parts = target[0].split()
    if parts[2] != "f2fs" or not parts[0].endswith("/userdata"):
        raise ValueError("Unexpected userdata device/filesystem")
    for required in ("fileencryption=", "metadata_encryption=", "keydirectory=", "wrappedkey_v0"):
        if required not in parts[4]:
            raise ValueError("Required existing encryption configuration missing")
    lines = old.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if data_lines(line):
            lines[i] = target[0] + "\n"
    return "".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=["moonstone"], required=True)
    parser.add_argument("--boot", type=Path, required=True)
    parser.add_argument("--expected-boot-sha256", required=True)
    parser.add_argument("--orangefox", type=Path, required=True)
    parser.add_argument("--fstab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parser.exit(2, "Эта адаптация OrangeFox отключена: проверка на moonstone завершилась зависанием на заставке. Не генерируйте и не прошивайте этот прототип.\n")
    boot, fox = args.boot.read_bytes(), args.orangefox.read_bytes()
    if digest(boot) != args.expected_boot_sha256 or digest(fox) != BASE_FOX_SHA256:
        raise ValueError("Input image checksum mismatch")
    kernel, _, os_version, cmdline = boot_v3(boot)
    _, fox_ramdisk, _, _ = boot_v3(fox)
    entries = cpio_entries(gzip.decompress(fox_ramdisk))
    if len({e[0] for e in entries}) != len(entries):
        raise ValueError("Duplicate archive entry")
    needed = {"init", "system/bin/init", "system/bin/recovery", "system/etc/recovery.fstab"}
    if not needed.issubset({e[0] for e in entries}):
        raise ValueError("Missing recovery boot components")
    original = {name: (fields, payload) for name, fields, payload in entries}
    current = args.fstab.read_text()
    adapted = []
    for name, fields, payload in entries:
        if name == "system/etc/recovery.fstab":
            payload = adapt_fstab(payload.decode(), current).encode()
        adapted.append((name, fields, payload))
    packed = encode_cpio(adapted)
    verified = cpio_entries(packed)
    for name, fields, payload in verified:
        if name != "system/etc/recovery.fstab" and (fields, payload) != original[name]:
            raise ValueError("Unintended ramdisk change")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "kernel").write_bytes(kernel)
    (out / "ramdisk.gz").write_bytes(gzip.compress(packed, mtime=0))
    version = os_version >> 11
    version_text = f"{version >> 14 & 127}.{version >> 7 & 127}.{version & 127}"
    patch = os_version & 2047
    patch_text = f"{2000 + (patch >> 4):04}-{patch & 15:02}"
    image = out / "OrangeFox-moonstone-UNTESTED-boot.img"
    subprocess.run(["mkbootimg", "--header_version", "3", "--kernel", str(out / "kernel"),
                    "--ramdisk", str(out / "ramdisk.gz"), "--cmdline", cmdline,
                    "--os_version", version_text, "--os_patch_level", patch_text,
                    "--output", str(image)], check=True)
    generated = image.read_bytes()
    new_kernel, new_ramdisk, new_os, new_cmdline = boot_v3(generated)
    if (new_kernel, new_os, new_cmdline) != (kernel, os_version, cmdline) or len(generated) > len(boot):
        raise ValueError("Boot metadata, kernel or partition-size validation failed")
    if gzip.decompress(new_ramdisk) != packed:
        raise ValueError("Ramdisk round-trip failed")
    report = {
        "status": "HOST_VALIDATED_ONLY_DO_NOT_FLASH_WITHOUT_DEVICE_REVIEW",
        "device": args.device, "boot_sha256": digest(boot), "base_fox_sha256": digest(fox),
        "candidate_sha256": digest(generated), "kernel_sha256": digest(kernel),
        "os_version": version_text, "os_patch_level": patch_text,
        "boot_partition_bytes": len(boot), "candidate_bytes": len(generated),
        "ramdisk_changed_entries": ["system/etc/recovery.fstab"],
        "limitations": ["Existing OrangeFox R11.1_2 beta binary ramdisk, not a new source build",
                        "AVB signature/footer not copied or forged; requires bootloader verification",
                        "Normal boot, touch, Android 17 decryption and recovery boot untested",
                        "No vendor_boot, DTBO, vbmeta or device partition changes"],
    }
    (out / "REPORT.json").write_text(json.dumps(report, indent=2) + "\n")
    (out / "SHA256SUMS").write_text(f"{digest(generated)}  {image.name}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
