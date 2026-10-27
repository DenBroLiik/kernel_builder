#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test actual zram slot functions under deterministic metadata interleavings.

Lock acquisition simulates a completed concurrent resize; slot unlock simulates
metadata replacement. I/O/codec APIs are stubbed, not the tested function bodies.
Optional argument: alternate zram_drv.c for a negative control.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1] / "kernel"
paths = [arg for arg in sys.argv[1:] if not arg.startswith("--")]
path = Path(paths[0]) if paths else root / "drivers/block/zram/zram_drv.c"
code = path.read_text()


def function(name):
    match = re.search(r"^static (?:ssize_t|int) " + name + r"\([^;{}]*\)\n\{", code, re.M)
    if not match:
        raise RuntimeError(name)
    end = code.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (code[end] == "{") - (code[end] == "}")
        end += 1
    return code[match.start():end]


prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <errno.h>
#define PAGE_SHIFT 12
#define PAGE_SIZE 4096
#define ZS_MM_RO 0
#define unlikely(x) (x)
#define pr_err(...) ((void)0)
typedef uint32_t u32;
enum { ZRAM_WB, ZRAM_SAME, ZRAM_IDLE, ZRAM_UNDER_WB };
struct slot { unsigned long handle, flags; };
struct zram { uint64_t disksize; struct slot *table; int init_lock; bool slot_locked; void *comp, *mem_pool; };
struct device { struct zram *zram; };
struct device_attribute { int unused; };
struct page { unsigned char data[PAGE_SIZE]; };
struct bio { int unused; };
struct bio_vec { struct page *bv_page; unsigned int bv_len, bv_offset; };
struct zcomp_strm { int unused; };
static struct zcomp_strm stream;
static struct zram *resize_target;
static bool replace_on_unlock;
static unsigned long read_entry;
static int stream_users, map_users, decode_error;
static unsigned char stored[PAGE_SIZE];
#define dev_to_zram(d) ((d)->zram)
#define sysfs_streq(a, b) (!strcmp(a, b))
#define init_done(z) ((z)->disksize != 0)
static void down_read(int *lock) {
    if (resize_target) {
        free(resize_target->table);
        resize_target->table = calloc(1, sizeof(struct slot));
        assert(resize_target->table);
        resize_target->table[0].handle = 42;
        resize_target->disksize = PAGE_SIZE;
        resize_target = NULL;
    }
    assert(!*lock); *lock = 1;
}
static void up_read(int *lock) { assert(*lock); *lock = 0; }
static void zram_slot_lock(struct zram *z, unsigned long index) {
    assert(index < (z->disksize >> PAGE_SHIFT) && !z->slot_locked); z->slot_locked = true;
}
static void zram_slot_unlock(struct zram *z, unsigned long index) {
    assert(z->slot_locked); z->slot_locked = false;
    if (replace_on_unlock) { z->table[index].handle = 999; replace_on_unlock = false; }
}
static bool zram_allocated(struct zram *z, unsigned long i) { assert(z->slot_locked); return z->table[i].handle != 0; }
static bool zram_test_flag(struct zram *z, unsigned long i, int flag) { assert(z->slot_locked); return !!(z->table[i].flags & (1UL << flag)); }
static void zram_set_flag(struct zram *z, unsigned long i, int flag) { assert(z->slot_locked); z->table[i].flags |= 1UL << flag; }
static unsigned long zram_get_handle(struct zram *z, unsigned long i) { assert(z->slot_locked); return z->table[i].handle; }
static unsigned long zram_get_element(struct zram *z, unsigned long i) { assert(z->slot_locked); return z->table[i].handle; }
static unsigned int zram_get_obj_size(struct zram *z, unsigned long i) { (void)z; (void)i; return 100; }
static int read_from_bdev(struct zram *z, struct bio_vec *b, unsigned long entry, struct bio *bio, bool partial) {
    (void)b; (void)bio; (void)partial; assert(!z->slot_locked); read_entry = entry; return 1;
}
static void *kmap_atomic(struct page *p) { map_users++; return p->data; }
static void kunmap_atomic(void *p) { (void)p; map_users--; }
static void zram_fill_page(void *p, unsigned int size, unsigned long value) {
    for (unsigned int i = 0; i < size / sizeof(value); i++) ((unsigned long *)p)[i] = value;
}
static void *zs_map_object(void *pool, unsigned long handle, int mode) { (void)pool; (void)handle; (void)mode; return stored; }
static void zs_unmap_object(void *pool, unsigned long handle) { (void)pool; (void)handle; }
static struct zcomp_strm *zcomp_stream_get(void *comp) { (void)comp; stream_users++; return &stream; }
static void zcomp_stream_put(void *comp) { (void)comp; stream_users--; }
static int zcomp_decompress(struct zcomp_strm *s, const void *src, unsigned int size, void *dst) {
    (void)s; (void)size; if (decode_error) return -EINVAL; memcpy(dst, src, PAGE_SIZE); return 0;
}
'''
harness = prefix + function("idle_store") + function("__zram_bvec_read")
harness += r'''
int main(int argc, char **argv) {
    (void)argv;
    struct zram z = {.disksize = PAGE_SIZE * 4};
    z.table = calloc(4, sizeof(struct slot)); assert(z.table);
    struct device device = {&z};
    if (argc == 1) {
    resize_target = &z;
    assert(idle_store(&device, NULL, "all", 3) == 3);
    assert(!z.init_lock && !z.slot_locked && (z.table[0].flags & (1UL << ZRAM_IDLE)));
    z.table[0].flags = 1UL << ZRAM_UNDER_WB;
    assert(idle_store(&device, NULL, "all", 3) == 3);
    assert(!(z.table[0].flags & (1UL << ZRAM_IDLE)));
    assert(idle_store(&device, NULL, "bad", 3) == -EINVAL);
    }
    struct page page;
    z.table[0].handle = 42; z.table[0].flags = 1UL << ZRAM_WB;
    replace_on_unlock = true;
    assert(__zram_bvec_read(&z, &page, 0, NULL, false) == 1);
    assert(read_entry == 42 && z.table[0].handle == 999 && !z.slot_locked);
    /* Existing decompression success/error paths must release mappings/stream. */
    z.table[0].flags = 0; memset(stored, 0xA5, sizeof(stored));
    assert(__zram_bvec_read(&z, &page, 0, NULL, false) == 0);
    assert(!memcmp(page.data, stored, PAGE_SIZE) && !map_users && !stream_users && !z.slot_locked);
    decode_error = 1;
    assert(__zram_bvec_read(&z, &page, 0, NULL, false) == -EINVAL);
    assert(!map_users && !stream_users && !z.slot_locked);
    free(z.table);
    puts("PASS: resize before init lock, idle/writeback exclusion, backing entry snapshot and read error cleanup");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="zram-slot-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(harness)
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O1", "-Wall", "-Wextra",
                    "-Werror", "-Wno-unused-parameter", "-Wno-sign-compare", "-fsanitize=address,undefined",
                    str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary), *( ["--read-only"] if "--read-only" in sys.argv else [])], check=True)
