#!/usr/bin/env bash
# Verify the daily installer refuses a module-enabled kernel before packaging.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
mkdir -p "$root/validation"
out=$(mktemp -d "$root/validation/zfs-package-test.XXXXXXXX")
echo 'CONFIG_MODULES=y' > "$out/.config"
if bash "$root/tools/package-stone.sh" "$out" > "$out/result.log" 2>&1; then
    echo 'FAIL: daily installer accepted a module-enabled profile' >&2
    exit 1
fi
grep -q 'Этот установщик не устанавливает модули' "$out/result.log"
echo 'PASS: daily packaging rejects module-enabled kernels before creating an archive'
