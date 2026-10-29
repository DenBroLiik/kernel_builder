#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test actual zram page detection and full-page decode validation functions."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
a = argparse.ArgumentParser()
a.add_argument('--zram-source', type=Path, default=root/'kernel/drivers/block/zram/zram_drv.c')
a.add_argument('--zcomp-source', type=Path, default=root/'kernel/drivers/block/zram/zcomp.c')
a.add_argument('--baseline', type=Path, help='Original zram_drv.c for the optional host benchmark')
a.add_argument('--benchmark', action='store_true')
args = a.parse_args()
def function(path, name):
    s = path.read_text()
    m = re.search(r'^(?:static )?(?:bool|int) '+name+r'\([^;{}]*\)\n\{', s, re.M)
    if not m:
        raise RuntimeError(name)
    end = s.index('{', m.start())+1
    depth = 1
    while depth:
        depth += (s[end]=='{')-(s[end]=='}')
        end += 1
    return s[m.start():end]

prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <time.h>
struct zcomp_strm { void *tfm; };
static unsigned int produced;
static int decode_error;
static int crypto_comp_decompress(void *tfm, const void *src, unsigned int len,
                                  void *dst, unsigned int *dst_len) {
    (void)tfm; (void)src; (void)len;
    assert(*dst_len == PAGE_SIZE);
    if(decode_error) return decode_error;
    memset(dst, 0x5a, produced <= PAGE_SIZE ? produced : PAGE_SIZE);
    *dst_len=produced; return 0;
}
'''
main = r'''
static void page_test(void) {
    size_t count=PAGE_SIZE/sizeof(unsigned long);
    unsigned long *page=malloc(PAGE_SIZE); assert(page);
    unsigned long patterns[]={0,~0UL,0x123456789abcdefUL,0x5555555555555555UL};
    for(size_t p=0;p<sizeof(patterns)/sizeof(*patterns);p++) {
        for(size_t i=0;i<count;i++) page[i]=patterns[p];
        unsigned long element=0;
        assert(page_same_filled(page,&element) && element==patterns[p]);
        for(size_t i=0;i<count;i++) {
            page[i]^=1UL<<(i%(8*sizeof(unsigned long)));
            element=0xdecaf;
            assert(!page_same_filled(page,&element));
            assert(element==0xdecaf); /* Failure must not change the output. */
            page[i]^=1UL<<(i%(8*sizeof(unsigned long)));
        }
    }
    free(page);
}
static void decode_test(void) {
    struct zcomp_strm s={0}; unsigned char *dst=malloc(PAGE_SIZE); assert(dst);
    unsigned char compressed[16]={0};
    unsigned int sizes[]={0,1,PAGE_SIZE-1,PAGE_SIZE,PAGE_SIZE+1};
    for(size_t i=0;i<sizeof(sizes)/sizeof(*sizes);i++) {
        produced=sizes[i]; decode_error=0; memset(dst,0xa5,PAGE_SIZE);
        int ret=zcomp_decompress(&s,compressed,sizeof(compressed),dst);
        assert(ret==(produced==PAGE_SIZE?0:-EIO));
        if(produced==PAGE_SIZE) for(size_t j=0;j<PAGE_SIZE;j++) assert(dst[j]==0x5a);
    }
    for(int error=-1;error>=-100;error--) {
        decode_error=error;
        assert(zcomp_decompress(&s,compressed,sizeof(compressed),dst)==error);
    }
    free(dst);
}
int main(void) {
    page_test(); decode_test();
    printf("PASS: %u-byte pages, every mismatch position, repeated words, decode size bounds and error propagation\n",PAGE_SIZE);
}
'''
bench = r'''
static volatile unsigned long sink;
static double measure(bool (*fn)(void*,unsigned long*),unsigned long *pages) {
    struct timespec start,end;
    bool (*volatile call)(void*,unsigned long*)=fn;
    clock_gettime(CLOCK_MONOTONIC,&start);
    for(int repeat=0;repeat<2000;repeat++) for(int n=0;n<64;n++) {
        unsigned long element=0;
        sink+=call(pages+n*(PAGE_SIZE/sizeof(unsigned long)),&element);
    }
    clock_gettime(CLOCK_MONOTONIC,&end);
    return ((end.tv_sec-start.tv_sec)*1e9+end.tv_nsec-start.tv_nsec)/(2000*64);
}
int main(void) {
    size_t words=PAGE_SIZE/sizeof(unsigned long);
    unsigned long *pages=calloc(64,PAGE_SIZE); assert(pages);
    for(int pattern=0;pattern<3;pattern++) {
        memset(pages,0,64*PAGE_SIZE);
        for(int n=0;n<64;n++) {
            if(pattern==0) pages[n*words+words-1]=n+1; /* Matching prefix, different tail. */
            if(pattern==1) pages[n*words+1]=n+1;       /* Early mismatch. */
        }
        for(int round=0;round<5;round++) {
            double before,after;
            if(round%2) {after=measure(page_same_filled,pages);before=measure(baseline_page_same_filled,pages);}
            else {before=measure(baseline_page_same_filled,pages);after=measure(page_same_filled,pages);}
            printf("pattern=%s round=%d before_ns=%.2f after_ns=%.2f\n",
                   pattern==0?"tail":(pattern==1?"early":"uniform"),round,before,after);
        }
    }
    free(pages); return sink==123456789UL;
}
'''
page_fn = function(args.zram_source, 'page_same_filled')
decode_fn = function(args.zcomp_source, 'zcomp_decompress')
with tempfile.TemporaryDirectory(prefix='zram-page-checks-') as work:
    cfile,binary=Path(work)/'test.c',Path(work)/'test'
    if args.benchmark:
        if args.baseline is None:
            a.error('--benchmark requires --baseline')
        old_fn=function(args.baseline,'page_same_filled').replace('page_same_filled','baseline_page_same_filled',1)
        functions=(page_fn+old_fn).replace('static bool ','static __attribute__((noinline)) bool ')
        cfile.write_text(prefix+functions+bench)
        subprocess.run(['cc','-std=gnu11','-O2','-DPAGE_SIZE=4096','-Wno-unused-function',str(cfile),'-o',str(binary)],check=True)
        subprocess.run([str(binary)],check=True)
    else:
        cfile.write_text(prefix+page_fn+decode_fn+main)
        for page_size in [4096,16384,65536]:
            subprocess.run(['cc','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',f'-DPAGE_SIZE={page_size}',str(cfile),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
