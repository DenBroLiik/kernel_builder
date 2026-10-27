#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Test the actual zs_compact entry point with threads and C11 atomics.

Page migration and class locks are stubbed. This verifies per-pool admission,
accounting and flag cleanup, not full kernel migration or reclaim behaviour.
"""
from pathlib import Path
import os
import re
import subprocess
import tempfile

source = Path(__file__).resolve().parents[1] / "kernel/mm/zsmalloc.c"
code = source.read_text()
match = re.search(r"^unsigned long zs_compact\([^)]*\)\n\{.*?^\}", code, re.M | re.S)
if not match:
    raise RuntimeError("zs_compact not found")
harness = r'''
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#define ZS_SIZE_CLASSES 4
typedef atomic_int atomic_t;
#define atomic_xchg(p, v) atomic_exchange(p, v)
#define atomic_set(p, v) atomic_store(p, v)
#define atomic_long_add(v, p) atomic_fetch_add(p, v)
struct size_class { int index; };
struct zs_pool {
    atomic_t compaction_in_progress;
    struct size_class *size_class[ZS_SIZE_CLASSES];
    struct { atomic_long pages_compacted; } stats;
    atomic_int entries;
    unsigned long result;
};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t changed = PTHREAD_COND_INITIALIZER;
static struct zs_pool *blocked_pool;
static bool entered, release_worker;
static unsigned long __zs_compact(struct zs_pool *pool, struct size_class *class)
{
    (void)class;
    atomic_fetch_add(&pool->entries, 1);
    pthread_mutex_lock(&lock);
    if (pool == blocked_pool) {
        entered = true;
        pthread_cond_broadcast(&changed);
        while (!release_worker) pthread_cond_wait(&changed, &lock);
    }
    pthread_mutex_unlock(&lock);
    return pool->result;
}
'''
harness += match.group()
harness += r'''
static void *worker(void *arg)
{
    unsigned long *ret = malloc(sizeof(*ret));
    assert(ret);
    *ret = zs_compact(arg);
    return ret;
}
int main(void)
{
    struct size_class merged = {.index = 2};
    struct zs_pool first = {.result = 3}, second = {.result = 5};
    /* A merged class appears twice and must only be processed once. */
    first.size_class[1] = first.size_class[2] = &merged;
    second.size_class[2] = &merged;
    blocked_pool = &first;
    pthread_t thread;
    assert(!pthread_create(&thread, NULL, worker, &first));
    pthread_mutex_lock(&lock);
    while (!entered) pthread_cond_wait(&changed, &lock);
    pthread_mutex_unlock(&lock);
    /* A concurrent pass on this pool must return without entering migration. */
    assert(zs_compact(&first) == 0);
    assert(atomic_load(&first.entries) == 1);
    /* Other pools must remain independent. */
    assert(zs_compact(&second) == 5);
    assert(atomic_load(&second.stats.pages_compacted) == 5);
    pthread_mutex_lock(&lock);
    release_worker = true;
    pthread_cond_broadcast(&changed);
    pthread_mutex_unlock(&lock);
    unsigned long *ret;
    assert(!pthread_join(thread, (void **)&ret));
    assert(*ret == 3); free(ret);
    assert(!atomic_load(&first.compaction_in_progress));
    assert(atomic_load(&first.stats.pages_compacted) == 3);
    assert(zs_compact(&first) == 3);
    first.result = 0;
    assert(zs_compact(&first) == 0);
    assert(!atomic_load(&first.compaction_in_progress));
    first.result = 2;
    assert(zs_compact(&first) == 2);
    assert(atomic_load(&first.stats.pages_compacted) == 8);
    /* Repeated empty passes must also release admission. */
    struct zs_pool empty = {0};
    for (int i = 0; i < 1000; i++) {
        assert(zs_compact(&empty) == 0);
        assert(!atomic_load(&empty.compaction_in_progress));
    }
    puts("PASS: per-pool concurrent compaction exclusion, independent pools, merged classes and accounting");
    return 0;
}
'''
harness = "#include <stdlib.h>\n" + harness
with tempfile.TemporaryDirectory(prefix="zs-compact-test-") as work:
    cfile = Path(work) / "test.c"
    binary = Path(work) / "test"
    cfile.write_text(harness)
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-Wall", "-Wextra",
                    "-Werror", "-fsanitize=address,undefined", "-pthread", str(cfile),
                    "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True, timeout=10)
