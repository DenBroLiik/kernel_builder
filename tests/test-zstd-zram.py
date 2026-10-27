#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise actual kernel zstd and crypto helpers with host allocation stubs.

The kernel's zstd 1.5.8 sources are compiled, not the host's libzstd. Only kernel
allocation/platform glue and xxhash are substituted. No device is accessed.
"""
import concurrent.futures
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1] / "kernel"
codec = root / "lib/zstd"
crypto = (root / "crypto/zstd.c").read_text()


def function(name):
    match = re.search(r"^static [^;{}]*\b" + name + r"\([^;{}]*\)\n\{", crypto, re.M)
    if not match:
        raise RuntimeError("Function missing: " + name)
    end = crypto.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (crypto[end] == "{") - (crypto[end] == "}")
        end += 1
    return crypto[match.start():end]


headers = {
    "linux/types.h": "#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\n#include <sys/types.h>\ntypedef uint8_t u8; typedef uint32_t u32; typedef uint64_t u64;\n",
    "linux/limits.h": "#include <limits.h>\n",
    "linux/stddef.h": "#include <stddef.h>\n#include <stdint.h>\n",
    "linux/string.h": "#include <string.h>\n",
    "linux/compiler.h": "#pragma once\n#define likely(x) (x)\n#define unlikely(x) (x)\n#define fallthrough __attribute__((fallthrough))\n",
    "linux/module.h": "#define EXPORT_SYMBOL(x)\n#define EXPORT_SYMBOL_GPL(x)\n#define MODULE_LICENSE(x)\n#define MODULE_DESCRIPTION(x)\n",
    "linux/swab.h": "#define swab32(x) __builtin_bswap32(x)\n#define swab64(x) __builtin_bswap64(x)\n",
    "linux/math64.h": "#include <stdint.h>\nstatic inline uint64_t div_u64(uint64_t a, uint32_t b) { return a / b; }\n",
    "linux/kernel.h": "#include <stdlib.h>\n#include <string.h>\n#define WARN_ON(x) ((x) ? (abort(), 1) : 0)\n",
    "linux/xxhash.h": "#pragma once\n#define XXH_STATIC_LINKING_ONLY\n#include <xxhash.h>\n#define xxh64_state XXH64_state_s\n#define xxh64 XXH64\n#define xxh64_reset XXH64_reset\n#define xxh64_update XXH64_update\n#define xxh64_digest XXH64_digest\n",
    "asm/unaligned.h": r'''
#pragma once
#include <stdint.h>
#include <string.h>
#define get_unaligned(p) ({ __typeof__(*(p)) v; memcpy((void *)&v, (p), sizeof(v)); v; })
#define put_unaligned(v, p) do { __typeof__(*(p)) tmp = (v); memcpy((p), &tmp, sizeof(tmp)); } while (0)
#define get_unaligned_le16(p) get_unaligned((const uint16_t *)(p))
#define get_unaligned_le32(p) get_unaligned((const uint32_t *)(p))
#define get_unaligned_le64(p) get_unaligned((const uint64_t *)(p))
#define put_unaligned_le16(v, p) put_unaligned(v, (uint16_t *)(p))
#define put_unaligned_le32(v, p) put_unaligned(v, (uint32_t *)(p))
#define put_unaligned_le64(v, p) put_unaligned(v, (uint64_t *)(p))
#define get_unaligned_be32(p) __builtin_bswap32(get_unaligned_le32(p))
#define get_unaligned_be64(p) __builtin_bswap64(get_unaligned_le64(p))
#define put_unaligned_be32(v, p) put_unaligned_le32(__builtin_bswap32(v), p)
#define put_unaligned_be64(v, p) put_unaligned_le64(__builtin_bswap64(v), p)
''',
}
prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <linux/zstd.h>
#define PAGE_SIZE 4096U
#define ZSTD_DEF_LEVEL 3
#define __init
#define __exit
static int live_allocs, alloc_calls, fail_at;
static void *vzalloc(size_t size) {
    void *p;
    alloc_calls++;
    if (alloc_calls == fail_at) return NULL;
    p = calloc(1, size);
    if (p) live_allocs++;
    return p;
}
static void vfree(void *p) { if (p) live_allocs--; free(p); }
/* Registration fault injection verifies init unwind as well. */
static int alg, scomp, zram_alg, reg_calls, reg_fail, registered;
static int reg_bit(void *p) { return p == &alg ? 1 : p == &scomp ? 2 : 4; }
static int crypto_register_alg(void *p) {
    if (++reg_calls == reg_fail) return -EINVAL;
    registered |= reg_bit(p); return 0;
}
static void crypto_unregister_alg(void *p) {
    assert(registered & reg_bit(p)); registered &= ~reg_bit(p);
}
#define crypto_register_scomp crypto_register_alg
#define crypto_unregister_scomp crypto_unregister_alg
'''
harness = prefix + re.search(r"struct zstd_ctx \{.*?\n\};", crypto, re.S).group()
harness += "\nstruct crypto_tfm { struct zstd_ctx ctx; };\n#define crypto_tfm_ctx(tfm) (&(tfm)->ctx)\n"
for name in ("zstd_comp_init", "zstd_decomp_init", "zstd_comp_exit", "zstd_decomp_exit",
             "__zstd_init", "zstd_zram_init", "__zstd_exit", "__zstd_compress",
             "__zstd_decompress", "zstd_mod_init", "zstd_mod_fini"):
    harness += "\n" + function(name) + "\n"
harness += r'''
int main(void)
{
    struct zstd_ctx generic = {0};
    struct crypto_tfm page_tfm = {0};
    struct zstd_ctx *page = &page_tfm.ctx;
    unsigned char *src = malloc(PAGE_SIZE * 2), *compressed = malloc(PAGE_SIZE * 2);
    unsigned char *decoded = malloc(PAGE_SIZE * 2);
    unsigned int seed = 1776;
    zstd_parameters gp = zstd_get_params(3, 0), pp = zstd_get_params(3, PAGE_SIZE);
    size_t generic_size = zstd_cctx_workspace_bound(&gp.cParams);
    size_t page_size = zstd_cctx_workspace_bound(&pp.cParams);
    assert(src && compressed && decoded && page_size < generic_size);
    for (int fail = 1; fail <= 2; fail++) {
        struct zstd_ctx ctx = {0};
        alloc_calls = 0; fail_at = fail;
        assert(__zstd_init(&ctx, PAGE_SIZE) < 0);
        assert(live_allocs == 0);
    }
    fail_at = 0;
    assert(__zstd_init(&generic, 0) == 0);
    assert(zstd_zram_init(&page_tfm) == 0);
    int allocations_after_init = alloc_calls;
    for (int pattern = 0; pattern < 4; pattern++) {
        for (unsigned int i = 0; i < PAGE_SIZE * 2; i++) {
            seed = seed * 1664525U + 1013904223U;
            src[i] = pattern == 0 ? 0 : pattern == 1 ? i % 31 :
                     pattern == 2 ? seed >> 24 : ((i / 32) % 127);
        }
        for (int writer = 0; writer < 2; writer++) {
            unsigned int length = PAGE_SIZE * 2;
            assert(__zstd_compress(src, PAGE_SIZE, compressed, &length,
                                   writer ? page : &generic) == 0);
            for (int reader = 0; reader < 2; reader++) {
                unsigned int out = PAGE_SIZE;
                struct zstd_ctx *target = reader ? page : &generic;
                /* A fresh decoder proves the frame needs no previous page. */
                target->dctx = zstd_init_dctx(target->dwksp, zstd_dctx_workspace_bound());
                assert(target->dctx);
                assert(__zstd_decompress(compressed, length, decoded, &out,
                                         target) == 0);
                assert(out == PAGE_SIZE && !memcmp(src, decoded, PAGE_SIZE));
            }
            unsigned int out = PAGE_SIZE;
            assert(__zstd_decompress(compressed, length / 2, decoded, &out, page) < 0);
        }
    }
    /* Generic zstd still handles non-page input; the zram profile rejects it. */
    for (unsigned int size = PAGE_SIZE / 2; size <= PAGE_SIZE * 2; size *= 4) {
        unsigned int length = PAGE_SIZE * 2, out = PAGE_SIZE * 2;
        assert(__zstd_compress(src, size, compressed, &length, &generic) == 0);
        assert(__zstd_decompress(compressed, length, decoded, &out, &generic) == 0);
        assert(out == size && !memcmp(src, decoded, size));
        out = PAGE_SIZE;
        assert(__zstd_decompress(compressed, length, decoded, &out, page) < 0);
        assert(__zstd_compress(src, size, compressed, &length, page) < 0);
    }
    unsigned int length = 1;
    assert(__zstd_compress(src, PAGE_SIZE, compressed, &length, page) < 0);
    memset(compressed, 0xA5, PAGE_SIZE);
    length = PAGE_SIZE;
    assert(__zstd_decompress(compressed, 100, decoded, &length, page) < 0);
    /* Failed output must not leave the reused context unusable. */
    length = PAGE_SIZE * 2;
    assert(__zstd_compress(src, PAGE_SIZE, compressed, &length, page) == 0);
    unsigned int recovered = PAGE_SIZE;
    page->dctx = zstd_init_dctx(page->dwksp, zstd_dctx_workspace_bound());
    assert(__zstd_decompress(compressed, length, decoded, &recovered, page) == 0);
    assert(recovered == PAGE_SIZE && !memcmp(src, decoded, PAGE_SIZE));
    assert(alloc_calls == allocations_after_init);
    __zstd_exit(page); __zstd_exit(&generic);
    assert(live_allocs == 0);
    for (int fail = 0; fail <= 3; fail++) {
        reg_calls = registered = 0; reg_fail = fail;
        int ret = zstd_mod_init();
        if (fail) { assert(ret < 0 && registered == 0); }
        else { assert(ret == 0 && registered == 7); zstd_mod_fini(); assert(registered == 0); }
    }
    printf("PASS: kernel ZSTD %s; generic workspace=%zu, page workspace=%zu, saved per stream=%zu bytes\n",
           ZSTD_VERSION_STRING, generic_size, page_size, generic_size - page_size);
    puts("PASS: independent-frame round trips, context recovery, size/corruption errors, allocation failure, cleanup and registration unwind");
    free(decoded); free(compressed); free(src);
    return 0;
}
'''

benchmark = "--benchmark" in sys.argv[1:]
if benchmark:
    bench = r'''
#include <time.h>
static double seconds(void) {
    struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1000000000.0;
}
static int benchmark_reuse(void) {
    const int iterations = 100000;
    zstd_parameters params = zstd_get_params(3, PAGE_SIZE);
    size_t size = zstd_cctx_workspace_bound(&params.cParams);
    void *memory[2] = {calloc(1, size), calloc(1, size)};
    zstd_cctx *ctx[2] = {zstd_init_cctx(memory[0], size), zstd_init_cctx(memory[1], size)};
    unsigned char *input = malloc(PAGE_SIZE * 16), *output = malloc(PAGE_SIZE * 2);
    unsigned int seed = 12345;
    volatile size_t checksum = 0;
    assert(ctx[0] && ctx[1] && input && output);
    for (unsigned int i = 0; i < PAGE_SIZE * 16; i++) {
        seed = seed * 1664525U + 1013904223U;
        input[i] = (i / PAGE_SIZE) % 4 == 0 ? seed >> 24 :
                   (i / PAGE_SIZE) % 4 == 1 ? i % 31 : (i / 32) % 127;
    }
    for (int round = 0; round < 5; round++) {
        double elapsed[2];
        for (int order = 0; order < 2; order++) {
            int mode = order ^ (round & 1);
            size_t ret = zstd_compress_cctx(ctx[mode], output, PAGE_SIZE * 2, input, PAGE_SIZE, &params);
            assert(!zstd_is_error(ret));
            double start = seconds();
            for (int i = 0; i < iterations; i++) {
                const unsigned char *page = input + (i % 16) * PAGE_SIZE;
                ret = mode ? zstd_compress_cctx_reuse(ctx[mode], output, PAGE_SIZE * 2, page, PAGE_SIZE) :
                             zstd_compress_cctx(ctx[mode], output, PAGE_SIZE * 2, page, PAGE_SIZE, &params);
                assert(!zstd_is_error(ret)); checksum += ret;
            }
            elapsed[mode] = seconds() - start;
        }
        printf("round=%d full=%.6f reuse=%.6f improvement_pct=%.2f\n", round,
               elapsed[0], elapsed[1], (elapsed[0] - elapsed[1]) * 100 / elapsed[0]);
    }
    printf("checksum=%zu\n", checksum);
    free(input); free(output); free(memory[0]); free(memory[1]);
    return 0;
}
'''
    harness = harness.replace("int main(void)\n{", bench + "\nint main(void)\n{\nreturn benchmark_reuse();", 1)

with tempfile.TemporaryDirectory(prefix="kernel-zstd-test-") as work:
    work = Path(work)
    for name in ("zstd.h", "zstd_lib.h", "zstd_errors.h"):
        headers["linux/" + name] = (root / "include/linux" / name).read_text()
    for name, data in headers.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data)
    test = work / "test.c"
    test.write_text(harness)
    sources = [test, codec / "zstd_compress_module.c", codec / "zstd_decompress_module.c"]
    for directory in ("common", "compress", "decompress"):
        sources += sorted((codec / directory).glob("*.c"))
    cc = os.environ.get("HOSTCC", "cc")
    flags = ["-std=gnu11", "-O2" if benchmark else "-O1", "-g", "-I" + str(work)]
    if not benchmark:
        flags += ["-fsanitize=address,undefined"]
    def compile_one(item):
        index, source = item
        obj = work / (str(index) + ".o")
        subprocess.run([cc, *flags, "-c", str(source), "-o", str(obj)], check=True)
        return obj
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        objects = list(pool.map(compile_one, enumerate(sources)))
    binary = work / "test"
    subprocess.run([cc, *flags, *map(str, objects), "-lxxhash", "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
