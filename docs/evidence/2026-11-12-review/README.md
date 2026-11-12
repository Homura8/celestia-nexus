# PR #1 review: independent boots and a second firmware stall

Independent reproduction during the PR #1 review, in a fresh Ubuntu 24.04
container (x86_64, 4 vCPUs, Firecracker VM) with Ubuntu's QEMU 8.2.2 and AAVMF
2024.02, the same distribution versions as the Linux CI job. Default target:
ordinary host clock, source-built loader. No proprietary Apple asset was used.

| File | Meaning |
| --- | --- |
| [boot-rate.json](boot-rate.json) | All 39 boots: 38 passed, 1 timed out. Conditions, versions, per-boot duration and, for later boots, when each stage was first seen |
| `firmware-stall-*` | The one failure: raw serial log, exact QEMU command, QMP state/registers and the run's `result.json` |

What this shows:

- **The baseline reproduces independently.** The HakiOS source was fetched
  through `NEXUS_MIRROR_HAKIOS` (a local clone of the locked commit), so the
  mirror path was exercised end to end; `operation.json` recorded the mirror.
- **The intermittent UEFI stall is real and not version-specific.** The failing
  boot printed the firmware banner, cleared the screen and never reached the
  loader; QMP reported a running vCPU with its PC inside firmware DXE code,
  the same picture as the original stall in
  [`2026-11-12/host-clock-stall-*`](../2026-11-12/README.md), which used QEMU
  10.0.13 with AAVMF 2025.02.
- **It was not reproducible on demand.** It occurred on the very first QEMU
  launch after installing QEMU in a freshly provisioned VM. The next 38 boots
  passed: 5 sequential runs, 20 runs four at a time, 4 runs after dropping the
  host page cache, and 8 complete `smoke` commands. Both recorded stalls happened
  inside a `smoke`, but 8 repeated smokes did not stall, so `smoke` itself is not
  established as the trigger. The root cause remains open.
- **A normal boot reaches the loader after about 7 seconds** of firmware time
  on this host (`stage_seconds` in boot-rate.json), so a run that shows only
  the firmware banner well past that point is stuck, not slow.

The stall's `result.json` predates the improved diagnosis: re-analysing its
serial log with the current code (`./nexus analyze ... --token ...`) reports
"Firmware started but never reached the loader". No retry was used to turn
the failure into a pass; it remains a failed experiment.
