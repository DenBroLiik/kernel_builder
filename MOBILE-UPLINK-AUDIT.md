# Mobile uplink investigation: WhatsApp video calls

## Observed symptom and limits

The user reports that, on MTS mobile data, the peer stops receiving their
audio/video while incoming audio/video continues, followed by WhatsApp's
reconnection message after approximately a minute. This narrows the symptom
to the outgoing stream; it does not identify the failing layer or endpoint.

A read-only device snapshot on 2026-10-28 showed LTE on rmnet_data2, a
validated default mobile network, and zero interface-reported errors/drops.
It was not captured during a reproduced failure. The running kernel reports
5.4.304-Eclipse; that string does not establish which source patches are
installed. Root kernel logs were unavailable because shell could not run su.
Private raw diagnostics remain under ignored validation/, outside Git.

## Confirmed source defect

In techpack/datarmnet/core/rmnet_map_data.c, both the ordinary aggregation
flush and QMAP control-packet flush cleared aggregation state and released
agg_lock before cancelling the flush timer. A valid interleaving is:

1. CPU A detaches the old aggregate and releases agg_lock.
2. CPU B creates a new aggregate and starts its flush timer under agg_lock.
3. CPU A cancels that new timer, leaving a pending aggregate without its
   scheduled flush.

Cancel the timer before releasing agg_lock. The hrtimer callback only
schedules agg_wq and does not acquire agg_lock; it can finish while the
canceller holds that lock. Do not synchronously cancel the work item under
agg_lock, because the work function does acquire it. QMAP flushing now uses
the same helper as normal flushing, preserving data-before-command order.

This defect can delay packets beyond the configured aggregation timeout.
Further incoming TX packets may flush the buffer through existing age/size
checks. It does not by itself explain a repeatable one-minute outage under
continuous traffic, and is not a confirmed cause of the reported call loss.
The path also requires uplink aggregation to be enabled by vendor setup.

## Validation

tests/test-rmnet-aggregation.py compiles actual driver functions with host
stubs. Its unlock hook schedules a second producer at the vulnerable point.
The unmodified source loses the new timer and fails an assertion; restoring
only the old QMAP function independently reproduces that failure. The patch
preserves the new timer in both cases, including empty QMAP flushing. Other
page-recycling, allocation-failure and clock/age tests remain in this test.
This is deterministic interleaving coverage, not a real modem concurrency
or radio performance measurement.

The full ARM64 daily kernel build (Image, DTBs, dtb.img and dtbo.img),
tests/test-tools.sh and kernel checkpatch passed. The linker still reports
stack-frame warnings in existing unrelated files. The source correction is
kernel commit 76ffa44c834a. No image containing this new correction has been
installed or tested during a WhatsApp call.

## Other code examined

- qmi_rmnet.c and dfc_qmi.c: bearer grants, stopped/woken TX queues, watchdog
  and flow-state transitions. No change to modem grants or flow control.
- ipa_v3/rmnet_ipa.c: suspend, power activation, outstanding-packet limits,
  completion wakeups and TX timeout. The timeout reports uplink stalls;
  blindly waking/resetting hardware here could violate modem backpressure.
- ipa_v3/ipa_dp.c: transmission completion and packet ownership.

No fixed one-minute timer causing this specific WhatsApp symptom has been
established. A simultaneous capture of TX queue backlog, driver stall logs,
radio state and app/network events during the failure is still needed to
distinguish driver, radio, operator path and application failure. No APN,
radio, DNS, audio setting, modem firmware or phone partition was changed.
