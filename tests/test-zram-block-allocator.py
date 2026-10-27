#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test actual zram backing-block allocation with atomic bitmap stubs.

--benchmark instead compares native single-thread searches using the actual
kernel find-bit implementation. It measures allocation only, not storage I/O.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1] / "kernel"
code = (root / "drivers/block/zram/zram_drv.c").read_text()


def function(text, name):
    match = re.search(r"^(?:static (?:inline )?)?(?:unsigned long|void) " + name + r"\([^;{}]*\)\n\{", text, re.M)
    if not match:
        raise RuntimeError(name)
    end = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <stdatomic.h>
#include <time.h>
#define BITS_PER_LONG (8UL * sizeof(unsigned long))
#define READ_ONCE(x) __atomic_load_n(&(x), __ATOMIC_RELAXED)
#define WRITE_ONCE(x, v) __atomic_store_n(&(x), (v), __ATOMIC_RELAXED)
#define atomic64_inc(p) atomic_fetch_add(p, 1)
#define atomic64_dec(p) atomic_fetch_sub(p, 1)
#define WARN_ON_ONCE(x) assert(!(x))
#define unlikely(x) (x)
#define min(a, b) ((a) < (b) ? (a) : (b))
#define round_down(x, y) ((x) & ~((y) - 1))
#define BITMAP_FIRST_WORD_MASK(x) (~0UL << ((x) % BITS_PER_LONG))
#define __ffs(x) __builtin_ctzl(x)
struct zram {
    unsigned long *bitmap, nr_pages, next_free_block;
    struct { atomic_long bd_count; } stats;
};
static int test_and_set_bit(unsigned long bit, unsigned long *map) {
    unsigned long mask = 1UL << (bit % BITS_PER_LONG);
    return !!(__atomic_fetch_or(&map[bit / BITS_PER_LONG], mask, __ATOMIC_SEQ_CST) & mask);
}
static int test_and_clear_bit(unsigned long bit, unsigned long *map) {
    unsigned long mask = 1UL << (bit % BITS_PER_LONG);
    return !!(__atomic_fetch_and(&map[bit / BITS_PER_LONG], ~mask, __ATOMIC_SEQ_CST) & mask);
}
'''
benchmark = "--benchmark" in sys.argv[1:]
if benchmark:
    find = (root / "lib/find_bit.c").read_text()
    prefix += function(find, "_find_next_bit") + function(find, "find_next_zero_bit")
else:
    prefix += r'''
static unsigned long find_next_zero_bit(const unsigned long *map, unsigned long size, unsigned long start) {
    for (unsigned long bit = start; bit < size; bit++)
        if (!(READ_ONCE(map[bit / BITS_PER_LONG]) & (1UL << (bit % BITS_PER_LONG)))) return bit;
    return size;
}
'''
harness = prefix + function(code, "alloc_block_bdev") + function(code, "free_block_bdev")
if benchmark:
    baseline = subprocess.check_output(["git", "show", "HEAD:drivers/block/zram/zram_drv.c"], cwd=root, text=True)
    harness += function(baseline, "alloc_block_bdev").replace("alloc_block_bdev(", "alloc_baseline(", 1)
    harness += r'''
static double seconds(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); return t.tv_sec + t.tv_nsec / 1e9; }
int main(void) {
    const unsigned long blocks = 65536, words = (blocks + BITS_PER_LONG - 1) / BITS_PER_LONG;
    struct zram z = {.nr_pages = blocks};
    z.bitmap = calloc(words, sizeof(unsigned long)); assert(z.bitmap);
    for (int round = 0; round < 5; round++) {
        double elapsed[2];
        for (int order = 0; order < 2; order++) {
            int mode = order ^ (round & 1);
            double start = seconds();
            for (int repeat = 0; repeat < 10; repeat++) {
                for (unsigned long w = 0; w < words; w++) z.bitmap[w] = 0;
                z.next_free_block = 1; atomic_store(&z.stats.bd_count, 0);
                for (unsigned long i = 1; i < blocks; i++)
                    assert((mode ? alloc_block_bdev(&z) : alloc_baseline(&z)) == i);
                assert((mode ? alloc_block_bdev(&z) : alloc_baseline(&z)) == 0);
            }
            elapsed[mode] = seconds() - start;
        }
        printf("round=%d baseline=%.6f nextfit=%.6f speedup=%.2fx\n", round, elapsed[0], elapsed[1], elapsed[0] / elapsed[1]);
    }
    free(z.bitmap); return 0;
}
'''
else:
    harness += r'''
static struct zram pool;
static atomic_int *owners;
static void *worker(void *unused) {
    (void)unused;
    for (;;) {
        unsigned long block = alloc_block_bdev(&pool);
        if (!block) break;
        assert(block < pool.nr_pages);
        assert(atomic_fetch_add(&owners[block], 1) == 0);
    }
    return NULL;
}
int main(void) {
    pool.nr_pages = 4097;
    pool.bitmap = calloc((pool.nr_pages + BITS_PER_LONG - 1) / BITS_PER_LONG, sizeof(unsigned long));
    owners = calloc(pool.nr_pages, sizeof(*owners)); assert(pool.bitmap && owners);
    pthread_t threads[4];
    for (int i = 0; i < 4; i++) assert(!pthread_create(&threads[i], NULL, worker, NULL));
    for (int i = 0; i < 4; i++) assert(!pthread_join(threads[i], NULL));
    assert(atomic_load(&owners[0]) == 0);
    assert(atomic_load(&pool.stats.bd_count) == (long)pool.nr_pages - 1);
    for (unsigned long b = 1; b < pool.nr_pages; b++) assert(atomic_load(&owners[b]) == 1);
    assert(alloc_block_bdev(&pool) == 0);
    free_block_bdev(&pool, 1); free_block_bdev(&pool, 3000);
    pool.next_free_block = 4000;
    unsigned long a = alloc_block_bdev(&pool), b = alloc_block_bdev(&pool);
    assert(a == 1 && b == 3000 && alloc_block_bdev(&pool) == 0);
    /* Stale, zero and out-of-range hints never claim reserved block zero. */
    for (int i = 0; i < 3; i++) {
        free_block_bdev(&pool, 23);
        pool.next_free_block = i == 0 ? 0 : i == 1 ? pool.nr_pages : 999999;
        assert(alloc_block_bdev(&pool) == 23 && alloc_block_bdev(&pool) == 0);
    }
    struct zram tiny = {.nr_pages = 1, .bitmap = pool.bitmap};
    assert(alloc_block_bdev(&tiny) == 0);
    tiny.nr_pages = 0;
    assert(alloc_block_bdev(&tiny) == 0);
    free(owners); free(pool.bitmap);
    puts("PASS: concurrent unique claims, full bitmap, wraparound, freed-block reuse, stale hints and reserved zero");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="zram-block-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(harness)
    args = [os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O2", "-pthread"]
    if not benchmark:
        args += ["-fsanitize=address,undefined"]
    subprocess.run([*args, str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=90)
