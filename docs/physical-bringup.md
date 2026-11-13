# Physical-device bring-up: an evidence-first route

This is a **research and debugging workflow**, not a flashing tool or a
grant of permission. Nexus has no live phone runner. Continue a real port
inside its authoritative repo (for example
[Homura8/g54-xnu](https://github.com/Homura8/g54-xnu)); use this document
and [port cases](port-cases/README.md) to avoid repeating expensive mistakes.
For the first real example, see [G54 lessons](g54-lessons.md).

## 1. The first 15 minutes: choose the path, not the patch

Search existing ports for the exact variant and then the **SoC/controller**,
including UniXNU's device registry, HakiOS's manifest and the shared
ruby/ios-spes/ios-qemu XNU lineage. Compare stock LK/direct-XNU, UEFI/UniXNU
and emulation. No universally best bootloader approach exists. Prove the
chosen path's minimum prerequisites before committing to a kernel patch.

Record in the port repository (dated and sourced, unknown if missing):

| Interface | Minimum evidence | Common traps |
| --- | --- | --- |
| Boot and recovery | Exact model, firmware, lock state, A/B mode, `fastboot boot` *execution*, matched stock restore image | Fastboot `OKAY` does not guarantee code ran; OTA/snapshot state changes |
| Kernel handoff | Boot-image format, entry EL, registers/DTB, PSCI, MMU granule, boot-args/ADT | A sibling board may enter at a different EL or pass a different FDT |
| CPU and memory | CPU MIDR/MPIDR, available banks, carveouts, GIC/interrupt/timer, watchdog | Mapping reserved memory or assuming all cores work |
| Visual diagnostics | Active display plane's actual base/stride/format, cache coherency | A firmware framebuffer tag may point to a *hidden* layer |
| Storage | Host/UIC state, PHY/reset/clocks, DMA, LUN/block size, partition and root type | Filesystem errors can be caused by an uninitialised controller |
| Userland | Real root mount, launchd PID 1, dyld/shared cache, backboardd/SpringBoard | An `exec` line is not an interactive GUI |
| Input | Active controller from DT overlay, power/clock, bus ID, firmware, report format, HID events | Wrong panel variant, flashless controller without firmware, touch scale |

Read-only facts collection should use a fixed command allowlist, bounded
timeouts, explicit device selection and sanitisation. Never implicitly treat
an unrelated `adb`/Fastboot device as the target. Stop before writes if the
owner, matching firmware, active slot, backups, recovery or OTA state is
uncertain. Never infer permission from another project or chat.

## 2. Run the shortest diagnostic ladder

One experiment = one hypothesis, one explicit input difference and one
observable acceptance criterion (except when a justified multi-change test
has independently readable outcomes). In the authoritative device repo,
retain a sanitised run card with source and build pins, kernel/boot-image hashes,
live preflight, method, observation, failure and rollback. Private evidence
stays ignored locally. An image that compiles has **not** booted.

1. **Image acceptance:** prove which bootloader command really executes code.
   Show an unmistakeable screen/serial marker and recover automatically or
   manually. If only flashing works, secure exact stock restoration first.
2. **Handoff:** instrument the bootloader-provided DT and *active scanout*,
   verify entry EL, memory window, timer, GIC and watchdog before XNU.
3. **XNU:** reach kernel entry, VM, IOKit, boot CPU IRQ and a persistent
   diagnostic channel; enable SMP only after the one-core path works.
4. **Storage:** separate UFS/other host link, logical units, partition
   parsing, read-only block I/O, HFS/APFS/ext filesystem and root mounting.
   Protect against writes until all previous layers pass.
5. **Userland:** inspect actual OS build, ABI, file ownership, dyld cache,
   launchd and distinct service checkpoints. Symbolicate sample PCs against
   the *same* userspace image before applying guessed workarounds.
6. **Display:** distinguish framebuffer writes, iOS-produced IOSurface
   presentation, lock screen, home screen, compositor correctness and fps.
7. **Input:** identify controller and power, prove bus transaction, load any
   required device-owned firmware locally, decode checksummed events, then
   confirm real physical interaction through the OS HID boundary.
8. **Reliability:** test restarts, buttons, power and crash recovery separately;
   keep the previous known-good image. Never convert a half-observed failure
   into a supported feature.

A saved trace that includes *where boot stopped* is often more valuable than a
new guess. The G54's E0–E27 run cards are linked by its
[case record](port-cases/g54-2026-11-13.json); do not substitute it for the
live project status.

## 3. Driver investigation without prematurely sharing drivers

For the rapidly changing November 2026 public driver ecosystem, consult the
[source-ranked community watch](research/2026-11-13-community-port-watch.md)
before treating another phone's claimed Metal, radio, camera or modem result
as applicable to this device. It distinguishes native and Android-hosted
boot paths, identifies the G54's PowerVR/Panfrost mismatch and records
reusable test boundaries without importing device-specific register writes.

For **graphics/GPU**, first collect frame timings, pixel format and colour
channel ordering, alpha/premultiplication, cache flushes, scanout plane order,
vsync/tearing and IOSurface presentation. Compare known-good QEMU CPU paths
before touching proprietary GPU command submission. CPU presentation at a
home screen does not prove acceleration; a future GPU path additionally
needs IOMMU/DMA, power, firmware, memory coherence, scheduling and a usable
userspace API bridge.

For **USB**, establish PHY/clocks/role, endpoint zero and a bounded serial
or bulk diagnostics channel before copying higher-level networking or gadget
logic. Prefer a reliable capture path for panics over ad-hoc camera footage.

For **Wi-Fi and Bluetooth**, identify exact PCIe/SDIO/USB/UART buses, radio
chip, firmware, power/clock/reset and transport independently; then solve
interrupts/DMA, driver-to-IOKit interfaces and userspace services. A device
tree entry or published service is not evidence of packets or pairing.

For **audio**, start with clocks/PMIC/codec, I2S/TDM/PCM path and one measurable
sample route, then output/input routing and userland audio services. A volume
slider moving on the screen is *not* audible output.

For **camera**, separate sensor ID/I2C, regulators/clock, MIPI CSI/ISP,
DMA/IOMMU, buffer format, camera framework and capture. Never infer a working
camera from a populated DT node.

For **power, RTC and keys**, start with matched PMIC/SPMI register evidence,
safe read-only probes and interrupt ownership. Long-press resets can originate
outside XNU. Never blindly program reset/power registers based on another
board. Key enumeration and battery placeholders are not functional policies.

Promote code to shared Nexus infrastructure only after **two real ports**
use the same well-defined interface (and licensing allows it). Until then,
document the mechanism, preconditions, measurements and source location.
Prefer fixing the active upstream driver rather than copying it.

## 4. Evidence hygiene and safe handoff

For each milestone write **expected vs observed**, timestamp, scope, exact
source/patched kernel, test-image hash (if publication is safe), current
firmware/slot, restore route and result. Mark host-only tests, owner reports,
upstream claims and proposals separately. Boot durations require a clear start,
end, root-state and background-work definition; do not compare a warm writable
root to a first boot as a controlled benchmark.

Each completed project should export only its highest-value public,
sanitised results into one
[port case](port-cases/README.md), pinned to the exact source commit. It
is a knowledge transfer, not an import of a device's firmware or drivers.
