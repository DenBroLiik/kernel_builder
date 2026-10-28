#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise the actual IPA WWAN TX function, including immediate completion."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = Path(os.environ.get('IPA_TEST_SOURCE', root / 'kernel/techpack/dataipa/drivers/platform/msm/ipa/ipa_v3/rmnet_ipa.c')).read_text()
match = re.search(r'^static netdev_tx_t ipa3_wwan_xmit\([^;{}]*\)\n\{', source, re.M)
if not match:
    raise RuntimeError('ipa3_wwan_xmit not found')
end = source.index('{', match.start()) + 1
depth = 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[match.start():end]
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
typedef int netdev_tx_t;
#define NETDEV_TX_OK 0
#define NETDEV_TX_BUSY 1
#define ETH_P_MAP 1
#define IPA_CLIENT_APPS_WAN_PROD 1
#define unlikely(x) (x)
#define htons(x) (x)
#define IPAWANERR_RL(...) ((void)0)
#define IPAWANERR(...) ((void)0)
#define IPAWANDBG_LOW(...) ((void)0)
struct sk_buff { unsigned int len, protocol; bool control; };
struct ipa3_wwan_private { int lock, outstanding_pkts; };
struct net_device {
    struct ipa3_wwan_private priv;
    struct { unsigned int tx_packets, tx_bytes, tx_dropped; } stats;
    bool stopped;
};
struct ctx {
    int ipa_config_is_apq, ap_suspend, outstanding_high, outstanding_high_ctl;
    int pm_hdl, q6_pm_hdl;
};
static struct ctx context;
static struct ctx *rmnet_ipa3_ctx = &context;
#define netdev_priv(d) (&(d)->priv)
#define atomic_read(a) (*(a))
#define atomic_inc(a) (++*(a))
#define atomic_dec(a) (--*(a))
#define RMNET_MAP_GET_CD_BIT(s) ((s)->control)
#define spin_lock_irqsave(l, f) do { f = 0; assert(!*(l)); *(l) = 1; } while (0)
#define spin_unlock_irqrestore(l, f) do { (void)(f); assert(*(l)); *(l) = 0; } while (0)
static int pm_result, dp_result, dp_calls, frees, deactivations[2];
static bool immediate_completion;
static struct net_device *active_dev;
static void dev_kfree_skb_any(struct sk_buff *s) { frees++; free(s); }
static void netif_stop_queue(struct net_device *d) { d->stopped = true; }
static bool netif_queue_stopped(struct net_device *d) { return d->stopped; }
static int ipa_pm_activate(int handle) { return handle == context.pm_hdl ? pm_result : 0; }
static void ipa_pm_deferred_deactivate(int handle) { assert(handle < 2); deactivations[handle]++; }
static int ipa3_tx_dp(int client, struct sk_buff *skb, void *meta) {
    (void)client; (void)meta; dp_calls++;
    assert(active_dev->priv.outstanding_pkts > 0);
    if (!dp_result && immediate_completion) {
        /* Simulate completion on another CPU before submit returns. */
        active_dev->priv.outstanding_pkts--;
        dev_kfree_skb_any(skb);
    }
    return dp_result;
}
'''
main = r'''
static struct net_device dev;
static struct sk_buff *reset(void) {
    dev = (struct net_device){0}; active_dev = &dev;
    context = (struct ctx){.outstanding_high = 4, .outstanding_high_ctl = 8,
                           .pm_hdl = 0, .q6_pm_hdl = 1};
    pm_result = dp_result = dp_calls = frees = 0;
    deactivations[0] = deactivations[1] = 0;
    immediate_completion = false;
    struct sk_buff *skb = malloc(sizeof(*skb)); assert(skb);
    *skb = (struct sk_buff){.len = 1234, .protocol = ETH_P_MAP}; return skb;
}
int main(void) {
    struct sk_buff *skb;
    const char *which = getenv("IPA_CASE");
    if (!which || which[0] == 's') {
        skb = reset(); immediate_completion = true;
        assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_OK);
        assert(frees == 1 && dev.stats.tx_packets == 1 && dev.stats.tx_bytes == 1234);
        assert(!dev.priv.outstanding_pkts && !dev.priv.lock);
    }
    skb = reset(); dp_result = -EPIPE;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_OK);
    assert(frees == 1 && dev.stats.tx_dropped == 1 && !dev.stats.tx_packets);
    assert(!dev.priv.outstanding_pkts && deactivations[0] == 1 && deactivations[1] == 1);
    skb = reset(); dp_result = -EPIPE; dev.priv.outstanding_pkts = 2;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_OK);
    assert(dev.priv.outstanding_pkts == 2 && !deactivations[0] && !deactivations[1]);
    skb = reset(); dp_result = -EFAULT;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_BUSY);
    assert(!frees && !dev.priv.outstanding_pkts && skb->len == 1234); free(skb);
    skb = reset(); context.ap_suspend = 1;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_BUSY);
    assert(dev.stopped && !dp_calls && !frees && !dev.priv.lock); free(skb);
    skb = reset(); pm_result = -EINPROGRESS;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_BUSY);
    assert(dev.stopped && !dp_calls && !frees); free(skb);
    skb = reset(); dev.priv.outstanding_pkts = context.outstanding_high;
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_BUSY);
    assert(dev.stopped && !dp_calls && !frees); free(skb);
    skb = reset();
    assert(ipa3_wwan_xmit(skb, &dev) == NETDEV_TX_OK);
    assert(dev.priv.outstanding_pkts == 1 && !frees && !deactivations[0]);
    assert(dev.stats.tx_packets == 1 && dev.stats.tx_bytes == 1234); free(skb);
    puts("PASS: IPA immediate completion, invalid-pipe PM cleanup, outstanding traffic and retry ownership");
}
'''
with tempfile.TemporaryDirectory(prefix='ipa-uplink-') as work:
    cfile, binary = Path(work) / 'test.c', Path(work) / 'test'
    cfile.write_text(prefix + function + main)
    subprocess.run(['cc', '-std=gnu11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-Wall', '-Wextra', '-Werror', str(cfile), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
