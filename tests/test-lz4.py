#!/usr/bin/env python3
"""Run the actual kernel LZ4 sources on the host with allocator fault injection.

Kernel allocation is stubbed; this tests codec correctness, allocation cleanup
and stack size, not target timing or the kernel allocator. No device access.
"""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
lz4 = root / "kernel/lib/lz4"
headers = {
    "linux/types.h": "#pragma once\n#include <stdint.h>\n#include <stddef.h>\n#include <stdbool.h>\n#include <sys/types.h>\n",
    "linux/compiler.h": "#pragma once\n#define likely(x) (x)\n#define unlikely(x) (x)\n",
    "linux/export.h": "#define EXPORT_SYMBOL(x)\n",
    "linux/string.h": "#include <string.h>\n",
    "linux/limits.h": "#include <limits.h>\n",
    "asm/simd.h": "/* ARM64 SIMD is disabled for this host-only test. */\n",
    "linux/slab.h": r'''
#pragma once
#include <stdlib.h>
#include <stdint.h>
#define GFP_NOWAIT 1U
#define __GFP_NOWARN 2U
extern int fail_alloc;
extern size_t live_allocs;
static inline void *kmalloc(size_t n, unsigned int flags)
{
    void *p;
    if (flags != (GFP_NOWAIT | __GFP_NOWARN)) abort();
    if (fail_alloc) return NULL;
    p = malloc(n);
    if (p) live_allocs++;
    return p;
}
static inline void *kmalloc_array(size_t n, size_t size, unsigned int flags)
{
    if (size && n > SIZE_MAX / size) return NULL;
    return kmalloc(n * size, flags);
}
static inline void kfree(void *p)
{
    if (p) live_allocs--;
    free(p);
}
''',
}
harness = r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lz4.h"
#include "lz4hc.h"
int fail_alloc;
size_t live_allocs;
int main(void)
{
    const int sizes[] = {1, 15, 4096, 65536};
    const int levels[] = {9, 10, 12};
    unsigned int seed = 1234567;
    char *input = malloc(65536), *output = malloc(LZ4_compressBound(65536));
    char *decoded = malloc(65536);
    void *state = malloc(LZ4_sizeofStateHC());
    assert(input && output && decoded && state);
    for (int pattern = 0; pattern < 3; pattern++) {
        for (int i = 0; i < 65536; i++) {
            seed = seed * 1664525U + 1013904223U;
            input[i] = pattern == 0 ? 0 : (pattern == 1 ? i % 31 : seed >> 24);
        }
        for (size_t s = 0; s < sizeof(sizes) / sizeof(*sizes); s++) {
            int size = sizes[s];
            int consumed = size;
            int length = LZ4_compress_destSize(input, output, &consumed, 512);
            assert(length > 0 && length <= 512 && consumed > 0 && consumed <= size);
            assert(LZ4_decompress_safe(output, decoded, length, consumed) == consumed);
            assert(!memcmp(input, decoded, consumed));
            assert(!live_allocs);
            for (size_t l = 0; l < sizeof(levels) / sizeof(*levels); l++) {
                length = LZ4_compress_HC(input, output, size,
                                        LZ4_compressBound(size), levels[l], state);
                assert(length > 0);
                assert(LZ4_decompress_safe(output, decoded, length, size) == size);
                assert(!memcmp(input, decoded, size));
                assert(!live_allocs);
                consumed = size;
                length = LZ4_compress_HC_destSize(state, input, output, &consumed, 512, levels[l]);
                assert(length > 0 && length <= 512 && consumed > 0 && consumed <= size);
                assert(LZ4_decompress_safe(output, decoded, length, consumed) == consumed);
                assert(!memcmp(input, decoded, consumed));
                assert(!live_allocs);
            }
        }
    }
    fail_alloc = 1;
    int consumed = 65536;
    assert(LZ4_compress_destSize(input, output, &consumed, 512) == 0);
    assert(LZ4_compress_HC(input, output, 65536, LZ4_compressBound(65536), 12, state) == 0);
    assert(!live_allocs);
    fail_alloc = 0;
    /* Recovery after an allocation failure and tiny output error paths. */
    assert(LZ4_compress_HC(input, output, 65536, LZ4_compressBound(65536), 12, state) > 0);
    consumed = 65536;
    assert(LZ4_compress_destSize(input, output, &consumed, 0) == 0);
    assert(LZ4_compress_HC(input, output, 65536, 0, 12, state) == 0);
    assert(!live_allocs);
    free(state); free(decoded); free(output); free(input);
    puts("PASS: LZ4/HC round trips, bounded output, allocation failure and cleanup; stack frames <= 4096 bytes");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="kernel-lz4-test-") as work:
    work = Path(work)
    for name, contents in headers.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    source = work / "test.c"
    source.write_text(harness)
    binary = work / "test"
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-O2",
                    "-DLZ4_FREESTANDING=1", "-DLZ4_FORCE_MEMORY_ACCESS=0",
                    "-Werror=frame-larger-than=4096", "-fsanitize=address,undefined",
                    "-I" + str(work), "-I" + str(lz4), str(source),
                    str(lz4 / "lz4.c"), str(lz4 / "lz4hc.c"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
