#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test actual BTC command sequencing with firmware-send fault injection.

Optional kernel root enables comparison against a baseline. Firmware and object
access are stubbed; this verifies retry/state/restart logic, not RF behaviour.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "kernel"
path = root / "drivers/staging/qca-wifi-host-cmn/os_if/linux/coex/src/wlan_cfg80211_coex.c"
code = path.read_text()
match = re.search(r"^static int\s+__wlan_cfg80211_coex_set_btc_chain_mode\([^;{}]*\)\n\{", code, re.M)
if not match:
    raise RuntimeError("BTC setter missing")
end = code.index("{", match.start()) + 1
depth = 1
while depth:
    depth += (code[end] == "{") - (code[end] == "}")
    end += 1
function = code[match.start():end]
harness = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>
#include <stdio.h>
typedef int QDF_STATUS;
struct coex_psoc_obj { int unused; };
struct wlan_objmgr_vdev;
struct wlan_objmgr_psoc { uint8_t mode; struct wlan_objmgr_vdev *vdevs[3]; bool valid; };
struct wlan_objmgr_vdev { struct wlan_objmgr_psoc *psoc; int id; };
#define QDF_IS_STATUS_ERROR(x) ((x) != 0)
#define QDF_IS_STATUS_SUCCESS(x) ((x) == 0)
#define qdf_status_to_os_return(x) ((x) ? -EIO : 0)
#define wlan_vdev_get_psoc(v) ((v)->psoc)
#define coex_err(...) ((void)0)
#define coex_debug(...) ((void)0)
#define COEX_CONFIG_BTC_CHAIN_MODE 0
#define wlan_objmgr_for_each_psoc_vdev(p, i, v) for ((i) = 0; (i) < 3; (i)++) if (((v) = (p)->vdevs[i]))
static struct coex_psoc_obj obj;
static int fail_send = -1, fail_get, fail_set, sends, restarts;
static int expected_old_mode, expected_new_mode;
static struct coex_psoc_obj *wlan_psoc_get_coex_obj(struct wlan_objmgr_psoc *p) { return p->valid ? &obj : NULL; }
static QDF_STATUS ucfg_coex_psoc_get_btc_chain_mode(struct wlan_objmgr_psoc *p, uint8_t *mode) { *mode = p->mode; return fail_get; }
static QDF_STATUS ucfg_coex_psoc_set_btc_chain_mode(struct wlan_objmgr_psoc *p, uint8_t mode) {
    if (fail_set) return 1;
    p->mode = mode; return 0;
}
static QDF_STATUS ucfg_coex_send_btc_chain_mode(struct wlan_objmgr_vdev *v, uint8_t mode) {
    assert(v->psoc->mode == expected_old_mode);
    assert(mode == expected_new_mode && restarts == 0);
    sends++;
    return v->id == fail_send;
}
static QDF_STATUS wlan_coex_config_updated(struct wlan_objmgr_vdev *v, int type) {
    (void)type;
    assert(v->psoc->mode == expected_new_mode && sends == 3);
    restarts++; return 0;
}
'''
harness += function
harness += r'''
int main(void)
{
    struct wlan_objmgr_psoc p = {.valid = true};
    struct wlan_objmgr_vdev v[3];
    for (int i = 0; i < 3; i++) { v[i].psoc = &p; v[i].id = i; p.vdevs[i] = &v[i]; }
    expected_old_mode = 0; expected_new_mode = 1;
    fail_send = 1;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EIO);
    assert(p.mode == 0 && sends == 2 && restarts == 0);
    fail_send = -1; sends = 0;
    /* Retry the exact same requested mode: must not return EALREADY. */
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == 0);
    assert(p.mode == 1 && sends == 3 && restarts == 3);
    sends = restarts = 0;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EALREADY);
    assert(!sends && !restarts);
    expected_old_mode = 1; expected_new_mode = 0;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 0, false) == 0);
    assert(p.mode == 0 && sends == 3 && !restarts);
    sends = 0; expected_old_mode = 0; expected_new_mode = 1; fail_set = 1;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EFAULT);
    assert(p.mode == 0 && sends == 3 && !restarts);
    fail_set = 0; fail_get = 1; sends = 0;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EFAULT);
    assert(!sends && !restarts);
    fail_get = 0;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(NULL, 1, true) == -EINVAL);
    v[0].psoc = NULL;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EINVAL);
    v[0].psoc = &p; p.valid = false;
    assert(__wlan_cfg80211_coex_set_btc_chain_mode(&v[0], 1, true) == -EINVAL);
    puts("PASS: BTC firmware failure, same-mode retry, commit ordering, delayed restart and invalid contexts");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="btc-mode-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(harness)
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-Wall", "-Wextra",
                    "-Werror", "-fsanitize=address,undefined", str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
