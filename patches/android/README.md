# Android Bluetooth A2DP queue correction

This is an Android Bluetooth source patch, not a kernel patch or a flashable
package. It has not been installed, Android-built or tested on the phone.

## Evidence

The saved POCO X5 5G log contains:

```
btif_a2dp_source_enqueue_callback: TX queue buffer size now=17 adding=12 max=28
```

The matching Android 17 reference callback adds the number of PCM frames
consumed by the encoder to the number of queued packet buffers. The callback
actually enqueues exactly one buffer. Thus 17 queued packets plus one incoming
packet is treated as 17 + 12 > 28, prematurely flushing the 17 old packets.
This also explains why the A2DP dropped/dropout counters cannot be interpreted
as direct measurements of over-the-air packet loss.

The patch compares queued packets with packet capacity before enqueueing the
one new packet. It retains the configured limit, the existing flush-on-full
policy, ordering, suspend flushing, codec frame statistics and overrun metrics.
It also reports the incoming count in packet units. It does not change codec,
sample rate, bitrate, Dolby, modem or radio parameters.

Retaining packets until the actual capacity is reached can retain more audio
than the old premature-flush behavior. Check latency as well as dropouts under
congestion when validating the ROM change.

## Reproduce host validation

From the builder root:

```sh
python3 tools/check-a2dp-queue-patch.py
```

This downloads one ~49 KB AOSP source file from the pinned revision, verifies
its SHA256, reproduces the premature flush using the actual callback, applies
the patch in a temporary directory, and runs the patched callback with ASan
and UBSan. Coverage includes the device's 17/12/28 case, full/near-full queues,
FIFO retention, frame counters and suspend flushing. It does not reproduce
real Bluetooth concurrency, radio behavior or the whole Android stack.

Reference repository: https://android.googlesource.com/platform/packages/modules/Bluetooth/

Reference branch/revision: android17-release,
`c77db469de80f86660bc053bec4dee0c5d4b947c`.

Reference file: `system/btif/src/btif_a2dp_source.cc`.

Reference file SHA256:
`b284008bc93447e4ad84aba564945270fe89f10847fd1d041f37ab451a50fdc8`.

The exact commit of the installed custom Bluetooth build has not been
established. The log matches the vulnerable expression's values, but a source
integration must still check the actual ROM tree and its local changes.

## ROM integration

Within the actual ROM's `packages/modules/Bluetooth` checkout, first review
its enqueue callback and check the patch against local changes:

```sh
git apply --check /home/developer/kernel_builder/patches/android/0001-a2dp-count-packets-at-queue-limit.patch
```

After applying/rebasing the correction, rebuild the Bluetooth component using
that ROM's build/signing setup. The kernel ZIP cannot carry this userspace
correction. Do not replace a running Bluetooth APK/APEX with the AOSP reference
file or treat the host test as a tested Android build.

## Review scope and remaining issue

The review also inspected the LDAC input/read/accounting wrapper, the AIDL FMQ
reader, libldac API/PCM buffer handling and ABR, and kernel btpower plus GENI
UART TX/RX DMA and runtime PM. The board DTS enables the GENI high-speed UART;
saved logs show the Qualcomm userspace Bluetooth HAL handling IBS. The kernel
HCI UART/QCA path is not selected in the daily build, while btusb is for USB
adapters. These are distinct code paths.

There is no confirmed codec-algorithm or kernel UART cause of the reported
sound gaps from this review. Available saved logs had PCM underflows and
queue-flush warnings, but no LDAC encoding-error or UART/IBS-failure messages.
This is limited log coverage, not proof that transport never fails.

The queue correction addresses the premature flushing, not the independent
PCM shortage reported by ReadAudioData. The phone disconnected before this
source review; its exact UART device binding, vendor HAL implementation and
installed Bluetooth build identity still need live verification.
