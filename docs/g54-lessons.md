# G54 → Nexus: evidence-backed porting lessons (13 November 2026)

**Source of truth:** [Homura8/g54-xnu](https://github.com/Homura8/g54-xnu),
especially [PR #7](https://github.com/Homura8/g54-xnu/pull/7) and its
`codex/ios-root-macos` branch. This review freezes commit
[`a1a9cba87ba5f03585a8f08386092254a8bd214b`](https://github.com/Homura8/g54-xnu/tree/a1a9cba87ba5f03585a8f08386092254a8bd214b).
**PR #7 is open and may advance**. Do not promote this snapshot's claims to
later hardware results automatically. Evidence is the source repo's
public run cards, generally owner observations; **Nexus has not booted or
touched the physical G54**. The compact machine-readable version is
[the port case](port-cases/g54-2026-11-13.json), viewable with
`python3 -m nexuslib.portcases show --id moto-g54-ios16-20261113`.

## 1. What was actually reached

| Stage | Source evidence at pinned commit | Outcome / boundary |
| --- | --- | --- |
| E0–E2: bootloader | [E0](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-12-e0-fastboot-boot.md), [E1](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-12-e1-g1-probe.md), E2 | `fastboot boot` acknowledged but did not run; stock-layout image flashed to `boot_a` displayed markers; reboot-mode + PSCI reset returned to Fastboot |
| E3–E5: handoff/XNU | [E4/E5](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-12-e5-xnu-first-boot.md) | Visible OVL0 L1 was *not* the address in `atag,videolfb`; EL1 entry, measured RAM, GIC, VM, XNU/IOKit and framebuffer output |
| E6–E14: UFS | [E6–E14](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-12-e6-e8-ufs.md) | LK left device in reset; MediaTek-ordered recovery gave link startup, device init and read-only LUN access |
| E15–E18: root/userland | [E15](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-12-e15-ios-root.md), E16/E18 | Host-validated HFS+ root + real launchd, six A55s verified; later iOS IOSurface display frames. Logs naming SpringBoard alone were not called a GUI |
| E20–E21: interface | [E20](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-13-e20-ufs-hs.md), [E21](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-13-e21-home-screen.md) | HS-G3 restoration and muted console coincided with much faster lock screen; synthetic swipe reached a home screen |
| E22–E26: touch | [E22](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-13-e22-touch-scan.md), [E26](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-13-e26-ios-touch.md) | Identified active Novatek controller, proved SPI3, downloaded local firmware, decoded big-endian multi-touch reports, confirmed physical iOS gestures |
| E27: keys | [E27](https://github.com/Homura8/g54-xnu/blob/a1a9cba87ba5f03585a8f08386092254a8bd214b/docs/experiments/2026-11-13-e27-keys.md) | Read three keys in a probe. Later resets correlated with pressing them; mechanism and iOS key integration remained unverified |

The current G54 fixes and kernel patch files live **there**, not here.
G54-specific addresses, Novatek firmware protocol, PMIC registers, vendor
SMCs, boot-image v4/gzip filler and iOS 16 HFS+ root format do **not**
automatically generalise. Revalidate all of them for new variants.

## 2. Failures worth remembering

**Bootloader contracts:** A host command returning `OKAY` proves only that
its protocol exchange completed. E0's `fastboot boot` is a direct
counterexample. Matching stock images, slot state, AVB and post-OTA merge are
safety preconditions, not an image format recipe to share with other devices.
E1 showed that watchdog reset and PSCI reset differ in whether Fastboot
receives the reboot-mode request.

**Framebuffer:** the firmware's tagged framebuffer may be invisible while a
different overlay is scanned out. E3 drew to an invisible region; E4 read
active display registers and established the visible stride before E5's
kernel patch. Also distinguish screen text from actual IOSurface content and
from a correctly composed UI.

**Storage:** E7's UFS `OCS=5` was below SCSI; E13's successful link produced
SCSI CHECK CONDITION; E14 completed `fDeviceInit` and read blocks, then
failed to mount F2FS as HFS+. This progression gives a portable diagnostic
taxonomy (link → UIC → SCSI → LUN → partition → filesystem) while none of
the G54 register values or reset calls is portable.

**Performance/causality:** E20 observed PWM-to-HS mode, a reported change from
30+ minutes to roughly 2–3 minutes for the lock screen, and console isolation.
It changed two orthogonal inputs and retained writable root state; this
is powerful evidence of a practical improvement, **not an isolated proof**
of how much time the link mode saved. E16 SMP and E18 DTrace decisions have
similar confounders. Preserve a known-good image and write one-variable tests
when possible; justify when hardware boot time makes a combined run rational.

**Touch:** E22's DT had multiple candidate controller nodes; the live panel
identified which one actually responded. E24 booted a **flashless** device
using a local OEM firmware blob; E25 rejected a plausible but wrong 12-bit
coordinate parser in favour of the stock module's 16-bit big-endian format
and checksum; E26 then attached to iOS HID. Don't share the firmware or
assume a successful SPI transfer proves usable touch. Polling works for the
milestone but IRQ/recovery remain separate work.

**Reboots:** E27 separated repeated SPMI reads (clean second boot) from
pressed-button runs (resets). Correlation is not an interrupt-controller or
PMIC long-press root cause. The G54 project must investigate before this
becomes a driver pattern.

## 3. Cross-check against other working approaches

The following are **source-inspected/upstream-reported**, not new Nexus
reproductions. Links are pinned to the reviewed public revisions:

| Project | Relevant path | Transferable boundary |
| --- | --- | --- |
| [ruby-ios-bringup](https://github.com/lky005/ruby-ios-bringup/tree/1aaa883755e546726b2f3a49a3ad099d77de4e62) | MT6877 direct LK → XNU 8796 → UFS → SpringBoard/touch, failure catalogue | Physical-phone stage markers, known-good restoration and one-variable experiments; its MT6877 framebuffer/PMIC and userland workarounds are not G54 defaults |
| [ios-spes](https://github.com/AdyaGMD/ios-spes/tree/bdc2682efd6398f61185eab398361b066bf93794) | Snapdragon SM7150, temporary boot → XNU → UFS/HFS+ → iOS UI | Same iOS ABI/HID/IOSurface milestones across a different vendor, but its Qualcomm GENI/RPMh and recovery semantics differ |
| [ios-qemu](https://github.com/lgrachov/ios-qemu/tree/8d23f48c683250c728a5c820482b450646453c02) | QEMU `virt` / HVF, software-composited iOS, virtio input/audio/network | Controls for OS-level services, CPU display, touch/HID and reproducible userland traces; not evidence of physical SoC drivers |
| [UniXNU](https://github.com/UniXNU/UniXNU/tree/dff276535db3ac394f628cec58a718cd46c20ac2) | Device/SoC registry, UEFI → DarwinBoot → XNU stages, profiles | Strong existing cross-device/OS architecture and adaptation checklists; a device UEFI and compatible OS profile remain prerequisites |

This comparison supports transferring **diagnostic contracts, stage records,
pins and privacy policy** first. Hardware-specific drivers should remain with
their active upstream/port. Licence review must precede any code movement:
XNU patches, framework scripts, upstream dependencies and proprietary blobs
can all have different rights.

## 4. What Nexus should learn next

The next G54 improvements worth recording are *measured* driver boundaries:
frame pacing/pixel format/alpha/vsync, a reliable USB log channel, key-reset
diagnostics, power and RTC facts, and independently proven bus/protocol/OS
integration for network, audio and camera. The
[physical bring-up guide](physical-bringup.md#3-driver-investigation-without-prematurely-sharing-drivers)
defines the checklists. Do not advertise a GPU, Wi-Fi, Bluetooth or audio
implementation until a real test on a named device confirms it.

The mechanism for future knowledge capture is a **new pinned case snapshot**
(and, only when demonstrated across ports, a shared utility). No G54 code or
proprietary materials were copied.
