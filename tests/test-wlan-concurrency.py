#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Compile the complete scan concurrency policy with deterministic API stubs.

Optional argument: alternate kernel root for a negative control. This checks
the final scan request after all overrides, not radio/firmware behaviour.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "kernel"
scan = root / "drivers/staging/qca-wifi-host-cmn/umac/scan/core/src"
code = (scan / "wlan_scan_manager.c").read_text()
header = (scan / "wlan_scan_main.h").read_text()


def function(name):
    match = re.search(r"^static [^;{}]*\b" + name + r"\([^;{}]*\)\n\{", code, re.M)
    if not match:
        raise RuntimeError("Missing function: " + name)
    end = code.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    return code[match.start():end]


fields = "adaptive_dwell_time_mode burst_duration dwell_time_active dwell_time_active_2g dwell_time_active_6g dwell_time_passive dwell_time_passive_6g idle_time max_rest_time min_rest_time n_probes num_bssid num_ssids repeat_probe_time scan_f_passive scan_type".split()
defaults = "active_dwell_time_6g_conc adaptive_dwell_time_mode_nc ap_scan_burst_duration conc_active_dwell conc_idle_time conc_max_rest_time conc_min_rest_time conc_passive_dwell go_scan_burst_duration passive_dwell_time_6g_conc sta_miracast_mcc_rest_time sta_scan_burst_duration".split()
prefix = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
enum { PM_SAP_MODE, PM_P2P_GO_MODE, PM_STA_MODE, PM_P2P_CLIENT_MODE, PM_NDI_MODE };
enum { QDF_SAP_MODE, QDF_P2P_GO_MODE, QDF_STA_MODE };
#define QDF_STATUS_SUCCESS 0
#define SCAN_TYPE_DEFAULT 0
#define QDF_MIN(a, b) ((a) < (b) ? (a) : (b))
struct wlan_objmgr_psoc { bool bt, sta2g, sap2g, dbs, mcc; unsigned modes[5], sap_peers, go_peers, freq; };
struct wlan_objmgr_pdev { struct wlan_objmgr_psoc *psoc; };
struct wlan_objmgr_vdev { struct wlan_objmgr_psoc *psoc; struct wlan_objmgr_pdev *pdev; struct { int vdev_opmode; } vdev_mlme; };
'''
prefix += "struct scan_start_request { struct wlan_objmgr_vdev *vdev; struct {\n"
prefix += "".join("unsigned int " + name + ";\n" for name in fields) + "} scan_req; };\n"
prefix += "struct wlan_scan_obj { bool miracast_enabled; struct {\n"
prefix += "".join("unsigned int " + name + ";\n" for name in defaults) + "} scan_def; };\n"
prefix += r'''
#define wlan_vdev_get_psoc(v) ((v)->psoc)
#define wlan_vdev_get_pdev(v) ((v)->pdev)
#define wlan_vdev_is_up(v) ((void)(v), QDF_STATUS_SUCCESS)
#define policy_mgr_is_sta_connected_2g(p) ((p)->sta2g)
#define policy_mgr_is_sap_go_on_2g(p) ((p)->sap2g)
#define policy_mgr_is_hw_dbs_capable(p) ((p)->dbs)
#define ucfg_scan_get_bt_activity(p) ((p)->bt)
#define policy_mgr_mode_specific_connection_count(p, mode, unused) ((p)->modes[mode])
#define policy_mgr_get_connection_count(p) ((p)->modes[0] + (p)->modes[1] + (p)->modes[2] + (p)->modes[3] + (p)->modes[4])
#define wlan_util_get_peer_count_for_mode(p, mode) ((mode) == QDF_SAP_MODE ? (p)->psoc->sap_peers : (p)->psoc->go_peers)
#define policy_mgr_current_concurrency_is_mcc(p) ((p)->mcc)
#define policy_mgr_is_mcc_in_24G(p) ((p)->mcc && (p)->sap2g)
#define policy_mgr_get_channel(p, mode, unused) ((p)->freq)
#define WLAN_REG_IS_5GHZ_CH_FREQ(f) ((f) >= 5000 && (f) < 5925)
#define WLAN_REG_IS_6GHZ_CHAN_FREQ(f) ((f) >= 5925)
#define wlan_reg_is_dfs_for_freq(p, f) ((void)(p), (f) >= 5260 && (f) <= 5720)
#define scm_debug(...) ((void)0)
struct probe_time_dwell_time { unsigned int dwell_time, probe_time; };
'''
for name in ("PASSIVE_DWELL_TIME_BT_A2DP_ENABLED", "SCAN_CTS_DURATION_MS_MAX",
             "SCAN_ROAM_SCAN_CHANNEL_SWITCH_TIME", "SCAN_DWELL_TIME_PROBE_TIME_MAP_SIZE",
             "SCAN_3PORT_CONC_SCAN_MAX_BURST_DURATION", "SCAN_BURST_SCAN_MAX_NUM_OFFCHANNELS",
             "SCAN_GO_MIN_ACTIVE_SCAN_BURST_DURATION", "SCAN_GO_BURST_SCAN_MAX_NUM_OFFCHANNELS",
             "SCAN_P2P_SCAN_MAX_BURST_DURATION", "SCAN_GO_MAX_ACTIVE_SCAN_BURST_DURATION"):
    prefix += re.search(r"^#define " + name + r"[^\n]*", header, re.M).group() + "\n"
for name in ("SCM_ACTIVE_DWELL_TIME_SAP", "SCM_ACTIVE_DWELL_TIME_NAN"):
    prefix += re.search(r"^#define " + name + r"[^\n]*", code, re.M).group() + "\n"
table_start = code.index("static const struct probe_time_dwell_time")
prefix += code[table_start:code.index("\n};", table_start) + 3]
prefix += function("scm_update_passive_dwell_time")
prefix += function("scm_scan_get_burst_duration")
prefix += function("scm_req_update_concurrency_params")
tests = r'''
static unsigned failures;
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); failures++; } } while (0)
int main(void)
{
    struct wlan_scan_obj scan = {.scan_def = {
        .conc_active_dwell = 40, .conc_passive_dwell = 110,
        .conc_max_rest_time = 100, .conc_min_rest_time = 50,
        .active_dwell_time_6g_conc = 60, .passive_dwell_time_6g_conc = 110 }};
    /* AP channel, DBS capability, BT audio, client presence, request mode, NDI. */
    const unsigned int frequencies[] = {2437, 5180, 5600};
    for (int band = 0; band < 3; band++)
    for (int dbs = 0; dbs < 2; dbs++)
    for (int bt = 0; bt < 2; bt++)
    for (int clients = 0; clients < 2; clients++)
    for (int request_sap = 0; request_sap < 2; request_sap++)
    for (int ndi = 0; ndi < 2; ndi++)
    for (int passive = 0; passive < 2; passive++) {
        struct wlan_objmgr_psoc p = {.sap2g = !band, .dbs = dbs, .bt = bt,
                                    .sap_peers = clients, .freq = frequencies[band]};
        p.modes[PM_SAP_MODE] = 1; p.modes[PM_NDI_MODE] = ndi;
        struct wlan_objmgr_pdev d = {&p};
        struct wlan_objmgr_vdev v = {.psoc = &p, .pdev = &d,
                                    .vdev_mlme = {request_sap ? QDF_SAP_MODE : QDF_STA_MODE}};
        struct scan_start_request r = {.vdev = &v, .scan_req = {
            .dwell_time_active = 50, .dwell_time_active_2g = 40,
            .dwell_time_passive = 110, .num_ssids = 1, .num_bssid = 1,
            .scan_f_passive = passive }};
        scm_req_update_concurrency_params(&v, &r, &scan);
        if (clients && (!dbs || !band)) CHECK(r.scan_req.dwell_time_active_2g <= 28);
        if (clients && (!dbs || band)) CHECK(r.scan_req.dwell_time_active <= 28);
        if (!band && !dbs && bt && !passive) CHECK(r.scan_req.dwell_time_passive <= 28);
        CHECK(r.scan_req.scan_f_passive == (unsigned int)passive);
        if (clients) CHECK(r.scan_req.min_rest_time == r.scan_req.max_rest_time);
        CHECK(r.scan_req.n_probes == r.scan_req.dwell_time_active / r.scan_req.repeat_probe_time);
        if (!clients && request_sap) CHECK(r.scan_req.dwell_time_active_2g == 40);
        /* No station/AP mutation is needed to test high SSID x BSSID counts. */
        r.scan_req.num_ssids = r.scan_req.num_bssid = 16;
        scm_req_update_concurrency_params(&v, &r, &scan);
        CHECK(r.scan_req.repeat_probe_time == scan_probe_time_dwell_time_map[SCAN_DWELL_TIME_PROBE_TIME_MAP_SIZE - 1].probe_time);
    }
    /* Idle radio, no AP: leave caller's dwell settings alone. */
    struct wlan_objmgr_psoc p = {0};
    struct wlan_objmgr_pdev d = {&p};
    struct wlan_objmgr_vdev v = {.psoc = &p, .pdev = &d, .vdev_mlme = {QDF_STA_MODE}};
    struct scan_start_request r = {.vdev = &v, .scan_req = {.dwell_time_active = 17, .dwell_time_passive = 110}};
    scm_req_update_concurrency_params(&v, &r, &scan);
    CHECK(r.scan_req.dwell_time_active == 17 && r.scan_req.dwell_time_passive == 110);
    if (failures) { fprintf(stderr, "%u failed assertions\n", failures); return 1; }
    puts("PASS: complete WLAN scan concurrency policy, 192 scenarios including passive/DFS scans and probe limits");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="wlan-policy-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(prefix + tests)
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-Wall", "-Wextra",
                    "-Werror", "-fsanitize=address,undefined", str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
