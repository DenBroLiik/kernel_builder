#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$root/kernel"
{
    git rev-parse HEAD
    git --no-pager -c color.ui=false diff --no-color --no-ext-diff --no-textconv --binary HEAD
    git -c core.excludesfile=/dev/null ls-files --others --exclude-standard -z | sort -z | xargs -0 -r sha256sum --
} | sha256sum | cut -d ' ' -f 1
