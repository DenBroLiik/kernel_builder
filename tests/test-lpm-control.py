#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0
"""Test LPM parameter/selection contracts using actual kernel function bodies.

Power-state selection and tick timing are stubbed; this is not a PSCI, wakeup
or device power test. Optional argument: alternate lpm-levels.c for baseline.
"""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1] / "kernel"
source = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "drivers/cpuidle/lpm-levels.c"
code = source.read_text()


def function(text, name):
    match = re.search(r"^(?:static )?(?:int|bool) " + name + r"\([^;{}]*\)\n\{", text, re.M)
    if not match:
        raise RuntimeError("Missing function: " + name)
    end = text.index("{", match.start()) + 1
    depth = 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[match.start():end]


declaration = re.search(r"^static bool (?:__read_mostly )?sleep_disabled[^;]*;\nmodule_param_named\(sleep_disabled[^;]*;", code, re.M).group()
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#define __read_mostly
struct kernel_param { void *arg; unsigned int perm; };
#define module_param_named(name, var, type, permissions) static struct kernel_param control = {&(var), permissions}
typedef int64_t ktime_t;
struct cpuidle_driver { int unused; };
struct cpuidle_device { int cpu; };
struct lpm_cpu { int unused; };
static struct lpm_cpu cpu;
static struct lpm_cpu *cpu_lpm = &cpu;
static ktime_t duration = 8000000;
static int selected, selection_calls;
#define TICK_NSEC 1000000
#define per_cpu(var, cpu_id) ((void)(cpu_id), (var))
#define ktime_to_us(v) ((v) / 1000)
static ktime_t tick_nohz_get_sleep_length(ktime_t *delta) { *delta = 0; return duration; }
static int cpu_power_select(struct cpuidle_device *dev, struct lpm_cpu *cpu, int64_t us) {
    (void)dev; (void)cpu; assert(us == duration / 1000); selection_calls++; return selected;
}
'''
harness = prefix + declaration + "\n"
harness += function((root / "lib/kstrtox.c").read_text(), "kstrtobool")
harness += "\n#define strtobool kstrtobool\n"
for name in ("param_set_bool", "param_get_bool"):
    harness += function((root / "kernel/params.c").read_text(), name) + "\n"
for name in ("lpm_sleep_disabled", "lpm_cpuidle_select"):
    harness += function(code, name) + "\n"
harness += r'''
int main(void)
{
    struct cpuidle_driver driver = {0};
    struct cpuidle_device dev = {0};
    bool stop = true;
    char value[8];
    /* Boot-time prohibition remains supported even with a writable parameter. */
    assert(param_set_bool("1", &control) == 0);
    assert(lpm_sleep_disabled());
    selected = 2;
    assert(lpm_cpuidle_select(&driver, &dev, &stop) == 0 && selection_calls == 0);
    /* Vendor power policy must be able to change this after boot. */
    assert((control.perm & 0220) == 0220);
    assert(param_set_bool("N", &control) == 0);
    assert(param_get_bool(value, &control) == 2 && !strcmp(value, "N\n"));
    assert(!lpm_sleep_disabled());
    assert(lpm_cpuidle_select(&driver, &dev, &stop) == 2 && selection_calls == 1);
    assert(param_set_bool("invalid", &control) == -EINVAL && !lpm_sleep_disabled());
    duration = TICK_NSEC; stop = true; selected = 0;
    assert(lpm_cpuidle_select(&driver, &dev, &stop) == 0 && !stop);
    cpu_lpm = NULL; stop = true;
    assert(lpm_cpuidle_select(&driver, &dev, &stop) == 0);
    cpu_lpm = &cpu;
    assert(param_set_bool(NULL, &control) == 0 && lpm_sleep_disabled());
    assert(param_get_bool(value, &control) == 2 && !strcmp(value, "Y\n"));
    puts("PASS: LPM boot prohibition, writable runtime control, idle selection and short timer handling");
    return 0;
}
'''
with tempfile.TemporaryDirectory(prefix="lpm-control-test-") as work:
    cfile, binary = Path(work) / "test.c", Path(work) / "test"
    cfile.write_text(harness)
    subprocess.run([os.environ.get("HOSTCC", "cc"), "-std=gnu11", "-Wall", "-Wextra",
                    "-Werror", "-Wno-unused-parameter", "-fsanitize=address,undefined",
                    str(cfile), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
