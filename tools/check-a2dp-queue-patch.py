#!/usr/bin/env python3
"""Validate the Android queue patch against its pinned AOSP reference.

Downloads one ~49 KB source file. Does not touch Android, the kernel or a ROM
checkout. Baseline and patched callbacks are tested in a temporary directory.
"""
from pathlib import Path
import base64
import hashlib
import subprocess
import tempfile
from urllib.request import urlopen

root = Path(__file__).resolve().parents[1]
revision = 'c77db469de80f86660bc053bec4dee0c5d4b947c'
relative = 'system/btif/src/btif_a2dp_source.cc'
expected = 'b284008bc93447e4ad84aba564945270fe89f10847fd1d041f37ab451a50fdc8'
url = f'https://android.googlesource.com/platform/packages/modules/Bluetooth/+/{revision}/{relative}?format=TEXT'
with urlopen(url, timeout=30) as response:
    encoded = response.read(1024 * 1024 + 1)
if len(encoded) > 1024 * 1024:
    raise RuntimeError('Unexpectedly large reference response')
source = base64.b64decode(encoded, validate=True)
if hashlib.sha256(source).hexdigest() != expected:
    raise RuntimeError('Reference source hash mismatch')
with tempfile.TemporaryDirectory(prefix='a2dp-reference-') as work:
    source_path = Path(work) / relative
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(source)
    command = ['python3', str(root/'tests/test-a2dp-packet-queue.py'), '--source', str(source_path)]
    baseline = subprocess.run(command, capture_output=True, text=True)
    if baseline.returncode == 0 or 'q.packets.size()' not in baseline.stderr:
        raise RuntimeError('Baseline did not reproduce the expected premature flush:\n' + baseline.stderr)
    print('PASS: pinned baseline reproduces premature queue flush', flush=True)
    patch = str(root/'patches/android/0001-a2dp-count-packets-at-queue-limit.patch')
    subprocess.run(['git', 'apply', '--check', patch], cwd=work, check=True)
    subprocess.run(['git', 'apply', patch], cwd=work, check=True)
    subprocess.run(command, check=True)
print('Android reference patch verified; installed ROM is unchanged.')
