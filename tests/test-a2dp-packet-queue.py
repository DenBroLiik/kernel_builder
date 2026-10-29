#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Compile the actual Android A2DP enqueue callback with a host packet queue."""
from pathlib import Path
import argparse
import re
import subprocess
import tempfile

parser = argparse.ArgumentParser()
parser.add_argument('--source', required=True, type=Path,
                    help='btif_a2dp_source.cc from the Android Bluetooth tree')
args = parser.parse_args()
source = args.source.read_text()
match = re.search(r'^static bool btif_a2dp_source_enqueue_callback\([^;{}]*\)\s*\{', source, re.M)
if not match:
    raise RuntimeError('enqueue callback not found')
end = source.index('{', match.start()) + 1
depth = 1
while depth:
    depth += (source[end] == '{') - (source[end] == '}')
    end += 1
function = source[match.start():end]
prefix = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <deque>
struct BT_HDR { uint16_t len, layer_specific; };
struct fixed_queue_t { std::deque<void*> packets; };
static size_t fixed_queue_length(fixed_queue_t* q) { return q->packets.size(); }
static void fixed_queue_enqueue(fixed_queue_t* q, void* p) { q->packets.push_back(p); }
static void* fixed_queue_try_dequeue(fixed_queue_t* q) {
    if(q->packets.empty()) return nullptr;
    void* p=q->packets.front(); q->packets.pop_front(); return p;
}
static void osi_free(void* p) { free(p); }
static void fixed_queue_flush(fixed_queue_t* q, void(*release)(void*)) {
    while(auto p=fixed_queue_try_dequeue(q)) release(p);
}
namespace log {
    template<typename... T> static void debug(const char*, T...) {}
    template<typename... T> static void warn(const char*, T...) {}
}
namespace bluetooth {
namespace common { static uint64_t time_get_os_boottime_us() { return 123456; } }
namespace metrics {
    static int reports;
    template<typename... T> static void LogMetricA2dpAudioOverrunEvent(T...) { reports++; }
}}
static int btif_av_source_active_peer() { return 0; }
static struct {
    fixed_queue_t* tx_audio_queue;
    bool tx_flush;
    uint64_t encoder_interval_ms;
    struct {
        size_t tx_queue_total_flushed_messages;
        uint64_t tx_queue_last_flushed_us;
        size_t tx_queue_dropouts;
        uint64_t tx_queue_last_dropouts_us;
        size_t tx_queue_max_dropped_messages;
        size_t tx_queue_total_dropped_messages;
        size_t tx_queue_total_frames;
        size_t tx_queue_max_frames_per_packet;
    } stats;
} btif_a2dp_source_cb;
static uint8_t btif_a2dp_source_dynamic_audio_buffer_size = 28;
static BT_HDR* packet() {
    auto p=static_cast<BT_HDR*>(malloc(sizeof(BT_HDR))); assert(p);
    *p={100,2}; return p;
}
'''
main = r'''
static void test(size_t initial, size_t frames) {
    fixed_queue_t q;
    btif_a2dp_source_cb={}; btif_a2dp_source_cb.tx_audio_queue=&q;
    btif_a2dp_source_cb.encoder_interval_ms=20;
    bluetooth::metrics::reports=0;
    for(size_t i=0;i<initial;i++) fixed_queue_enqueue(&q,packet());
    void* oldest=initial?q.packets.front():nullptr;
    assert(btif_a2dp_source_enqueue_callback(packet(),frames,1024));
    bool full=initial>=28;
    assert(q.packets.size()==(full?1:initial+1));
    assert(btif_a2dp_source_cb.stats.tx_queue_total_dropped_messages==(full?initial:0));
    assert(btif_a2dp_source_cb.stats.tx_queue_dropouts==(full?1u:0u));
    assert(bluetooth::metrics::reports==(full?1:0));
    assert(btif_a2dp_source_cb.stats.tx_queue_total_frames==frames);
    assert(btif_a2dp_source_cb.stats.tx_queue_max_frames_per_packet==frames);
    if(initial&&!full) assert(q.packets.front()==oldest);
    fixed_queue_flush(&q,osi_free);
}
int main() {
    /* Exact device log: now=17 adding=12 max=28. One packet is added. */
    test(17,12);
    for(size_t n : {0u,1u,17u,27u,28u,29u})
        for(size_t frames : {1u,2u,12u,15u}) test(n,frames);
    fixed_queue_t q;
    btif_a2dp_source_cb={}; btif_a2dp_source_cb.tx_audio_queue=&q;
    for(int n=0;n<3;n++) fixed_queue_enqueue(&q,packet());
    btif_a2dp_source_cb.tx_flush=true;
    assert(!btif_a2dp_source_enqueue_callback(packet(),12,1024));
    assert(q.packets.empty());
    assert(btif_a2dp_source_cb.stats.tx_queue_total_flushed_messages==3);
    assert(btif_a2dp_source_cb.stats.tx_queue_total_frames==0);
    puts("PASS: A2DP device case, FIFO preservation, packet capacity boundary, frame statistics and suspend flush");
}
'''
with tempfile.TemporaryDirectory(prefix='a2dp-queue-') as work:
    cfile, binary = Path(work)/'test.cc', Path(work)/'test'
    cfile.write_text(prefix+function+main)
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fno-builtin-log',
                    '-fsanitize=address,undefined',str(cfile),'-o',str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
