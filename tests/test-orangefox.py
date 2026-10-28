#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Check the recovery archive adapter against system cpio, without a phone."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adapter", root / "tools/prepare-orangefox.py")
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


def rejected(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("Unsafe input accepted")


with tempfile.TemporaryDirectory(prefix="orangefox-test-") as work:
    base = Path(work)
    source, dest = base / "source", base / "restored"
    source.mkdir()
    dest.mkdir()
    (source / "init").write_bytes(b"unchanged executable\n")
    (source / "init").chmod(0o755)
    (source / "link").symlink_to("init")
    old = "/dev/block/by-name/userdata /data f2fs noatime wait,fileencryption=old\n"
    (source / "fstab").write_text(old)
    archive = subprocess.run(["cpio", "-o", "--format=newc", "--quiet"],
                             input=b"init\nlink\nfstab\n", cwd=source,
                             check=True, capture_output=True).stdout
    entries = adapter.cpio_entries(archive)
    repacked = adapter.encode_cpio(entries)
    subprocess.run(["cpio", "-id", "--quiet", "--no-absolute-filenames"],
                   input=repacked, cwd=dest, check=True, capture_output=True)
    assert (dest / "init").read_bytes() == (source / "init").read_bytes()
    assert (dest / "init").stat().st_mode & 0o777 == 0o755
    assert (dest / "link").readlink() == Path("init")
    assert (dest / "fstab").read_text() == old
    rejected(lambda: adapter.cpio_entries(archive[:80]))
    rejected(lambda: adapter.cpio_entries(b"bad" * 100))
    rejected(lambda: adapter.boot_v3(b"ANDROID!"))
    current = ("/dev/block/by-name/userdata /data f2fs noatime,flush_merge "
               "wait,fileencryption=aes-256-xts:aes-256-cts:v2+wrappedkey_v0,"
               "metadata_encryption=aes-256-xts:wrappedkey_v0,keydirectory=/metadata/vold\n")
    assert adapter.adapt_fstab(old, current) == current
    rejected(lambda: adapter.adapt_fstab(old, current + current))
    rejected(lambda: adapter.adapt_fstab(old, current.replace("fileencryption=", "removed=")))
    rejected(lambda: adapter.adapt_fstab(old, current.replace("f2fs", "ext4")))
    output = base / "must-not-be-created"
    blocked = subprocess.run([sys.executable, str(root / "tools/prepare-orangefox.py"),
                              "--device", "moonstone", "--boot", str(base / "missing-boot.img"),
                              "--expected-boot-sha256", "0" * 64,
                              "--orangefox", str(base / "missing-fox.img"),
                              "--fstab", str(base / "missing-fstab"), "--output", str(output)],
                             capture_output=True, text=True)
    assert blocked.returncode == 2 and "отключена" in blocked.stderr
    assert not output.exists()
print("PASS: real cpio interoperability, executable mode, symlink, truncated inputs and encryption-preserving fstab adaptation")
print("PASS: known-failing recovery prototype cannot generate another image")
