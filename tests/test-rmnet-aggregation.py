#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Exercise actual RMNET aggregation functions with host packet/clock stubs."""
from pathlib import Path
import os
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = Path(os.environ.get("RMNET_TEST_SOURCE", root / "kernel/techpack/datarmnet/core/rmnet_map_data.c")).read_text()

def function(name):
    match = re.search(r"^(?:static )?(?:struct page \*|void )" + name + r"\([^;{}]*\)\n\{", source, re.M)
    if not match:
        raise RuntimeError(name)
    end, depth = source.index("{", match.start()) + 1, 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[match.start():end]

prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#define unlikely(x) (x)
#define RMNET_PAGE_RECYCLE 1
#define RMNET_EGRESS_FORMAT_PRIORITY 2
#define RMNET_EGRESS_FORMAT_AGGREGATION 4
#define GFP_ATOMIC 0
#define ETH_P_MAP 1
#define HRTIMER_MODE_REL 0
#define htons(x) (x)
#define ns_to_ktime(x) (x)
static void (*unlock_hook)(void);
static void test_unlock(int *lock) {
    assert(*lock == 1); *lock = 0;
    if (unlock_hook) { void (*hook)(void) = unlock_hook; unlock_hook = NULL; hook(); }
}
#define spin_lock_irqsave(lock, flags) do { flags = 0; assert(!*(lock)); *(lock) = 1; } while (0)
#define spin_unlock_irqrestore(lock, flags) do { (void)(flags); test_unlock(lock); } while (0)
struct list_head { struct list_head *next, *prev; };
#define list_entry(p, type, member) ((type *)((char *)(p) - offsetof(type, member)))
#define list_next_entry(p, member) list_entry((p)->member.next, __typeof__(*(p)), member)
#define list_first_entry(h, type, member) list_entry((h)->next, type, member)
static int list_is_last(struct list_head *p, struct list_head *h) { return p->next == h; }
static void add_tail(struct list_head *n, struct list_head *h) {
    n->next = h; n->prev = h->prev; h->prev->next = n; h->prev = n;
}
struct page { int refs, id; };
struct rmnet_agg_page { struct page *page; struct list_head list; };
struct timespec64 { long tv_sec, tv_nsec; };
struct sk_buff { int len, priority, protocol, room; void *dev; };
struct rmnet_port {
    struct rmnet_agg_page *agg_head;
    struct list_head agg_list;
    struct { int agg_features, agg_size, agg_count; long agg_time; } egress_agg_params;
    struct { struct { int ul_agg_reuse, ul_agg_alloc; } agg; } stats;
    int data_format, agg_size_order, agg_lock, agg_count, agg_state, hrtimer;
    struct sk_buff *agg_skb;
    struct timespec64 agg_last, agg_time;
};
static int allocations, ref_checks, sends, timers, allocation_fail;
static struct page fallback = {1, 999};
static int page_ref_count(struct page *p) { ref_checks++; return p->refs; }
static void page_ref_inc(struct page *p) { p->refs++; }
static struct page *__dev_alloc_pages(int flags, int order) {
    (void)flags; (void)order; allocations++; return allocation_fail ? NULL : &fallback;
}
static long mono, wall;
static struct timespec64 stamp(long ns) { return (struct timespec64){ns / 1000000000L, ns % 1000000000L}; }
static void ktime_get_ts64(struct timespec64 *t) { *t = stamp(mono); }
static void ktime_get_real_ts64(struct timespec64 *t) { *t = stamp(wall); }
static struct timespec64 timespec64_sub(struct timespec64 a, struct timespec64 b) {
    return stamp((a.tv_sec-b.tv_sec)*1000000000L+a.tv_nsec-b.tv_nsec);
}
static long rmnet_agg_bypass_time = 10000000, rmnet_agg_time_limit = 1000000;
static struct sk_buff buffer;
static void dev_queue_xmit(struct sk_buff *s) { (void)s; sends++; }
static void dev_kfree_skb_any(struct sk_buff *s) { (void)s; }
static int skb_tailroom(struct sk_buff *s) { return s->room - s->len; }
static struct sk_buff *rmnet_map_build_skb(struct rmnet_port *p) {
    (void)p; buffer = (struct sk_buff){.room = 4096}; return &buffer;
}
static void rmnet_map_linearize_copy(struct sk_buff *d, struct sk_buff *s) { d->len += s->len; }
static struct rmnet_port *rmnet_get_port(void *dev) { return dev; }
static void hrtimer_start(int *t, long ns, int mode) { *t = 1; (void)ns; (void)mode; timers++; }
static void hrtimer_cancel(int *t) { *t = 0; }
'''
main = r'''
static void pool_test(int count, int busy) {
    struct rmnet_port p = { .egress_agg_params.agg_features = RMNET_PAGE_RECYCLE };
    struct rmnet_agg_page entries[8]; struct page pages[8];
    p.agg_list.next = p.agg_list.prev = &p.agg_list;
    for (int i = 0; i < count; i++) {
        pages[i] = (struct page){busy ? 2 : 1, i};
        entries[i].page = &pages[i]; add_tail(&entries[i].list, &p.agg_list);
    }
    p.agg_head = count ? &entries[0] : NULL;
    for (int round = 0; round < 30; round++) {
        allocations = ref_checks = 0;
        struct page *got = rmnet_get_agg_pages(&p);
        if (busy || !count) {
            assert(got == &fallback && allocations == 1);
            assert(ref_checks <= count && ref_checks <= 6);
        } else {
            assert(got == &pages[round % count] && got->refs == 2);
            assert(!allocations); got->refs--;
        }
        if (count) {
            assert(p.agg_head != (void *)((char *)&p.agg_list - offsetof(struct rmnet_agg_page, list)));
        }
    }
    if (count > 1) {
        for (int i = 0; i < count; i++) pages[i].refs = 2;
        p.agg_head = &entries[count - 1]; pages[0].refs = 1;
        assert(rmnet_get_agg_pages(&p) == &pages[0]);
    }
}
static void timing_test(void) {
    struct rmnet_port p = { .egress_agg_params = {.agg_size = 4096, .agg_count = 20, .agg_time = 3000000} };
    struct sk_buff packet = {.len = 100};
    sends = timers = 0;
    mono = 1000000000L; wall = 100000000000L;
    rmnet_map_tx_aggregate(&packet, &p);
    assert(sends == 1 && !p.agg_skb); /* Sparse traffic goes immediately. */
    mono += 100000; wall += 100000;
    rmnet_map_tx_aggregate(&packet, &p);
    assert(sends == 1 && p.agg_count == 1 && timers == 1);
    mono += 100000; wall -= 90000000000L; /* Wall-clock rollback. */
    rmnet_map_tx_aggregate(&packet, &p);
    assert(sends == 1 && p.agg_count == 2);
    mono += 100000; wall += 200000000000L; /* Wall-clock jump forward. */
    rmnet_map_tx_aggregate(&packet, &p);
    assert(sends == 1 && p.agg_count == 3 && timers == 1);
    mono += 2000000; wall += 2000000;
    rmnet_map_tx_aggregate(&packet, &p);
    assert(sends == 2 && p.agg_count == 1); /* Normal age flush still works. */
}
static struct rmnet_port *interleaved_port;
static void start_next_aggregate(void) {
    struct sk_buff packet = {.len = 100};
    rmnet_map_tx_aggregate(&packet, interleaved_port);
}
static void cancellation_race_test(bool command) {
    struct sk_buff old = {.len = 100};
    struct rmnet_port p = {
        .egress_agg_params = {.agg_size = 4096, .agg_count = 20, .agg_time = 3000000},
        .data_format = RMNET_EGRESS_FORMAT_AGGREGATION,
        .agg_skb = &old, .agg_count = 1, .agg_state = -EINPROGRESS, .hrtimer = 1
    };
    mono = 1000000000L; p.agg_last = stamp(mono - 100000);
    sends = timers = 0;
    interleaved_port = &p;
    /* A second producer acquires agg_lock at the first unlock. */
    unlock_hook = start_next_aggregate;
    if (command) {
        struct sk_buff cmd = {.dev = &p};
        rmnet_map_tx_qmap_cmd(&cmd);
    } else {
        unsigned long flags;
        spin_lock_irqsave(&p.agg_lock, flags);
        rmnet_map_send_agg_skb(&p, flags);
    }
    assert(p.agg_skb && p.agg_count == 1 && p.agg_state == -EINPROGRESS);
    assert(p.hrtimer == 1 && timers == 1); /* New batch still has a flush timer. */
    assert(sends == (command ? 2 : 1) && !p.agg_lock);
}
static void empty_flush_test(void) {
    struct rmnet_port p = {.data_format = RMNET_EGRESS_FORMAT_AGGREGATION};
    struct sk_buff cmd = {.dev = &p};
    sends = 0;
    rmnet_map_tx_qmap_cmd(&cmd);
    assert(sends == 1 && !p.agg_lock && !p.hrtimer);
}
int main(void) {
    for (int n = 0; n <= 8; n++) { pool_test(n, 0); pool_test(n, 1); }
    allocation_fail = 1;
    struct rmnet_port empty = {0};
    assert(!rmnet_get_agg_pages(&empty));
    timing_test();
    cancellation_race_test(false);
    cancellation_race_test(true);
    empty_flush_test();
    puts("PASS: RMNET recycled-page wrap, busy/empty pools, bounded search, allocation failure, clock jumps, age flush and interleaved data/QMAP timer cancellation");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix="rmnet-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(prefix + function("rmnet_get_agg_pages") + function("rmnet_map_send_agg_skb") + function("rmnet_map_tx_aggregate") + function("rmnet_map_tx_qmap_cmd") + main)
    subprocess.run(["cc", "-std=gnu11", "-O1", "-g", "-fsanitize=undefined", "-Wall", "-Wextra", "-Wno-unused-function", str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
