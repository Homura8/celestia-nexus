# Community Apple-OS port watch — 13 November 2026

**Scope:** Public developments reported approximately 3–13 November 2026,
especially HakiOS, Scion, independent XNU phone ports, r/hackios and the
oosexgang developer announcements. **Research only:** no upstream code,
proprietary OS image, firmware, credential, private device data, flash command
or new verified Nexus device support is introduced here.

This is a **dated snapshot**, not a compatibility list. A video is a useful
lead, not an independently verified device test. Repository `main` may change
after the exact commit links below. The existing [G54 owner-observed
case](../port-cases/g54-2026-11-13.json) and [lessons](../g54-lessons.md)
remain the authority for that device's observed milestone.

## 1. How to read the evidence

| Grade | Meaning | Consequence for Nexus |
| --- | --- | --- |
| N — Nexus reproduced | Our runner/experiment artifacts establish the milestone | May be a Nexus-supported experimental recipe |
| P — source-pinned, upstream hardware account | Public code and author-maintained hardware logs/instructions describe a device run; Nexus has **not** reproduced it | Inspect architecture, compare against the target, independently test |
| R — source-pinned, offline or partially verified | Public implementation/test exists, but the claimed hardware path is pending, narrower, or only simulated | Good specification or test candidate; no hardware success label |
| D — original demonstration/report only | First-person post, photo, short video or channel announcement without a matching reproducible build/run card | Discovery lead; request logs, code, exact hardware and a cold-boot demonstration |
| H — hypothesis/proposal | Inference, planned driver, future target or performance claim without qualifying measurements | Never report as working |

The grades apply **per claim**, not globally to a repository. They are not
trust scores for people. Useful proof includes exact firmware/OS build, target
revision, warm/cold boot distinction, kernel-entry/PID1/UI evidence,
driver-specific readback, a failure log, and observable restoration to stock.
Frame-rate claims require a frame counter and scene/resolution, not just
panel refresh or a visually smooth clip. A cellular status-bar icon does not
prove a functioning mobile-data route.

## 2. What changed, by independent lineage

| Lineage and public source | Reported milestone and actual mechanism | Grade / unresolved boundary |
| --- | --- | --- |
| [HakiOS MT6768 / Infinix Hot 20](https://github.com/oosexgang/hakios-mt6768/tree/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285), [shared `mtk` branch](https://github.com/oosexgang/hakios-xnu-kernel/tree/a962798418fa1ebaa06554a69955803860907c6b) | Direct XNU/iOS 16.5 line: CONNSYS Wi-Fi, Apple80211-facing adapter, Mali/Panfrost Metal work and an MT6631 Bluetooth HCI path. The channel [reports](https://t.me/s/oosexgangdevs) Wi-Fi, Bluetooth and Metal, 10–11 Nov. | **P** for documented MT6768 hardware trials; **R** for the *generic* BT skeleton (compiled, never used on a second phone). See §3. |
| [HakiOS “iOS 27.2 on redwood”](https://t.me/s/oosexgangdevs), [news mirror](https://hackios.net/en/news) | 11–12 Nov posts/screenshots claim iOS 27.2 home screen, Wi-Fi and first Metal frames on `redwood`. | **D** for iOS 27.2 specifically: the pinned public MT6768 README documents iOS **16.5**; an About page and a launch image alone cannot establish the loaded kernel and real userland version. Request the corresponding 27 source/build and boot log. |
| [Scion Galaxy S9 Exynos 9810](https://github.com/Scion-Project/scion-kernel/tree/2a79ef85e4bf1fe17bc94e3d1db58ba1d78aa247/docs/ios27) and [installer](https://github.com/Scion-Project/scion-installer/tree/e14ff4b2876f4f5c1cafc49b40784d0bc92b9866) | Separately documented **native direct XNU iOS 27.0.1** on S9 `starlte`, with iPhone 11 userland, XNU 12377, ARM instruction AOT rewrite, software/OpenGL ES renderer and experimental Metal/PanVK. Test phone reached lock screen; installer repository's regular zip still targets iOS 16.5. | **P** for reported iOS 27 boot on *S9*, **R/H** for unreplicated clean userland build and experimental Metal. **No** Wi-Fi/audio/BT/cellular on its 27 line; documented destructive USERDATA process must not be copied into generic automation. See §5. |
| [Galaxy S7 `herolte` / Exynos 8890](https://github.com/wardevsa/ios-a5xelte/tree/ff2c55e19f1a66fb811ed85bd17a21de9fc727bf/docs/herolte-howto.md), [original report](https://www.reddit.com/r/hackios/comments/1xpu4qm/) | Native iOS 16.7.16, Mali-T880 Mesa/Panfrost **OpenGL ES** with double-buffered display, eight CPUs, touch, WPA2 Wi-Fi, speaker; stock Metal and many peripherals not working. | **P** for owner-described phone runs; no Nexus reproduction. CPU scheduling, compositor validity, Wi-Fi firmware handoff and actual measured FPS are separate questions. |
| [Galaxy S9+ `star2lte` / Exynos 9810](https://github.com/danstronics/ios-s9plus-exynos/tree/2d092398040f98685b0c5a07776df5e9f199b9dc), [report](https://www.reddit.com/r/hackios/comments/1xpfotf/) | Installed XNU/iOS 16.5 BOOT + read-only SYSTEM on UFS, volatile Data, functional touch, GLES/Panfrost Mali-G72, Wi-Fi association/DHCP/DNS/SSH. Installer verifies matching BOOT and unchanged RECOVERY; has recovery timeout. | **P** for source-pinned installed run; **H** for Metal→Vulkan (separate WIP) and stable 60 fps. S9+ result must not be attributed to S9 native iOS 27 above. |
| [Pixel 5 `redfin`](https://github.com/maxexcloo/ios-redfin/tree/db05400e97fdcff14c2bfcb6a3ed18e0baa8187e), [upstream](https://github.com/DenialOfGravity/ios-redfin/tree/fb7149ada5b5adb41b4a8941d3504d54fc7bea3d), [cellular announcement](https://www.reddit.com/r/hackios/comments/1xreerj/) | Native XNU/iOS 16.7.16 path with Adreno Metal/direct scanout and measured scene-specific FPS. Original developer reports a short-lived **LTE web page and SMS**; the `maxexcloo` fork explicitly marks cellular as **imported, not yet verified on that fork**. | **P** for upstream narrow data/SMS proof, **R** for the fork's modem changes. Not stable mobile data, calls, IMS or a usable phone. See §4. |
| [Galaxy S20 Exynos 990](https://www.reddit.com/r/hackios/comments/1xq95wf/), [ISP/cellular update](https://www.reddit.com/r/hackios/comments/1xt8j74/), [camera](https://www.reddit.com/r/hackios/comments/1xtcibu/camera_is_up/), [game](https://www.reddit.com/r/hackios/comments/1xuker1/) | Original posts (5–12 Nov) show progressive native iOS 16.5 display, touch, configurable 60/120Hz, claimed Metal2Vulkan, Wi-Fi/BT/audio, live camera preview and a running game; author describes an earlier **ISP frames not arriving at XNU** and cellular work borrowing redfin lessons. | **D**: no verified matched public source/driver run card located. Camera preview is meaningful but not evidence of saved full-resolution capture; a game clip does not establish GPU timing; modem remains in progress. |
| [OneiOS on Galaxy S24 Ultra](https://github.com/akshaynexus/OneiOS/tree/c2d281a69b14915bc153c54b5120e30de7526a9d), [OneOS fork](https://github.com/akshaynexus/OneOS/tree/784bf335a949843893bfb54e153ac239c261fb0c), [original post](https://www.reddit.com/r/hackios/comments/1xu5atn/) | iOS 27.0.1 **hosted on One UI's running Linux kernel**, with source-built XNU in a userspace process (`runtime/xnuhost`) and host bridges. Author's test phone reaches lock/Home screen with touch and partial GPU; root is temporary; return to One UI. | **P** for logged *hosted* trials; **not** native direct LK/ABL→XNU, universal GSI or proof that locked Snapdragon S24 accepts a normal iOS boot image. See §6. |
| [Scion Tensor G5 / Pixel 10](https://scion-project.github.io/) | Separate **Android AVF/pKVM virtualization** experiment, distinct from native S9 line. | **D/R** pending matching code/run artifacts. Do not combine Scion project names into one boot method. |
| [Asoft no-root Android VM](https://github.com/alpersamur3/asoft-ios-android/releases/tag/v0.1.4), [release post](https://www.reddit.com/r/hackios/comments/1xtm0ln/) | Android app/VM-style experiment advertised for iOS 16/26 and watchOS; user reports long cold boot on Galaxy S25 Ultra. | **D** for exact runtime/feature claims, **not** native direct boot. Useful to examine only for a separate hosted test path. |
| [Redmi Note 11 Pro 4G `viva`](https://github.com/Nik300/viva-gpu/tree/54011de06784d259d509d588839d2e739c6260c6), [post](https://www.reddit.com/r/hackios/comments/1xo0drx/) | Mali-G57 Metal→AIR/NIR→Panfrost design with detailed shader and mocked GPU tests. | **R, not hardware GPU success** at pinned README: explicitly says kernel GPU interface missing, tests done on Mac; linked [`Nik300/ios-viva` main](https://github.com/Nik300/ios-viva/tree/45263bee51df4a0f55cdf9c649af886399488ddb) still contains an `ios-sweet` / Snapdragon Redmi Note 10 Pro README. Resolve branch and build provenance before treating the Reddit GPU claim as source-proven. |
| [Pixel Fold Tensor G2](https://www.reddit.com/r/hackios/comments/1xnoclc/) | 4 Nov author claims native Metal on Mali-G710, first-pass thermal control and remaining glitches. | **D**: no corresponding pinned source+hardware record established in this review. “Native Metal” needs clarification (actual Apple driver, translated API, or custom Metal implementation). |
| [Xiaomi 11 Lite NE (`lisa`)](https://www.reddit.com/r/hackios/), [Xiaomi 17 Pro Max](https://www.reddit.com/r/hackios/comments/1xotmrp/), [Mi 10 (`umi`)](https://www.reddit.com/r/hackios/) | Screenshots/videos report iOS UI, touch and varying peripherals, including a Mi 10 LTE status-bar icon. | **D**; no matched source/test artifact in this review; these do **not** prove boot mode, stable connectivity, cellular data or general-device driver support. |

**Chronology warning:** source snapshots and social posts evolve hourly; the
Scion S9 iOS 27 report, HakiOS `redwood` iOS 27 screenshots and hosted S24
iOS 27 are **three different code paths**. Do not copy a device's claim into
another lineage merely because the version string is the same.

## 3. MediaTek radio: strongest near-term reusable work

**Read first:** [HakiOS MTK BT porting guide at pinned SHA](https://github.com/oosexgang/hakios-mt6768/blob/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285/docs/bluetooth-mtk-porting.md),
[MT6768 Wi-Fi notes](https://github.com/oosexgang/hakios-mt6768/blob/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285/docs/wifi-x6826b.md),
and [shared MTK XNU code](https://github.com/oosexgang/hakios-xnu-kernel/tree/a962798418fa1ebaa06554a69955803860907c6b).

The BT guide separates iOS-facing `bluetoothd`/Skywalk/kernel-control plumbing
from a **platform-owned transport**. On the MT6768/MT6631 hardware, author logs
report all **six HCI initialization commands** answered, CoreBluetooth manager
state `5` and six BLE devices discovered in ten seconds. **Pairing, A2DP,
call audio and reconnect reliability are not established by those results.**
The generic `redwood_mtkbt_skel.c` has compiled and linked with a stub
platform, **but has not run on a different phone**. It requires explicit
chip power/ROM patch, firmware/WMT sequence, H4 send/receive/reassembly and
the local Wi-Fi/BT address; it declines to publish a controller if handshake
checks fail. It has mutually exclusive registration with the original
MT6768-specific code, so blindly enabling both is wrong.

The Wi-Fi notes explicitly divide the portable Apple80211/station/network
API from the **nonportable** MT6631 CONNSYS power, AXI, DMA/interrupts,
firmware and station-join implementation. The old plan dated 27 October is
not itself evidence of current Wi-Fi completion; later hardware claims live
in MT6768 code/author runs. `mt76`, Qualcomm ath11k and S7 Broadcom do **not**
automatically supply a driver for an unrelated MediaTek combination chip.

**G54 handoff:** before proposing any MTK radio driver, inventory the actual
MT6855 board's connectivity chip ID, `compatible` values, bus, IRQ, clocks,
regulators, reserved memory, Android driver/module names, firmware identity
and whether Wi-Fi and BT share a powered CONNSYS. Compare each field against
the MT6768 table. Only if the **physical transport matches** should an agent
test a platform adapter for the existing high-level API; record which pieces
are copied/rewritten and their licences. Start with read-only chip-ID and
power-state logs, then a version request and one scan, not an unsupported
claim of paired audio.

## 4. What the modem and camera reports really contribute

The [original Pixel 5 mobile-data/SMS report](https://www.reddit.com/r/hackios/comments/1xreerj/)
says Google loaded over LTE **once** and the connection dropped almost
immediately. This is a **cellular data path proof**, not a modem support
completion. A [maintained fork's README](https://github.com/maxexcloo/ios-redfin/blob/db05400e97fdcff14c2bfcb6a3ed18e0baa8187e/README.md)
clearly separates the upstream data/SMS claim from what was tested on the
fork. The S20 author explicitly cited this lineage while tackling cellular.

Transferable modem **investigation** order: identify baseband protocol,
transport endpoints, power and SIM readiness; capture an Android baseline
for registration; distinguish registration, IP session establishment,
DNS/TCP/browser success, packet persistence, SMS send/receive and calls/IMS;
observe drops and reconnect. Qualcomm QMI/rmnet internals are **not** a
ready-made MT6855 modem driver; use a transport-neutral state/metrics model
only after the Moto-specific stock stack is mapped. Do not publish SIM IDs,
carrier credentials or modem calibration data.

The [S20 ISP post](https://www.reddit.com/r/hackios/comments/1xt8j74/)
identifies a useful stage boundary: camera sensor/ISP frame creation can
succeed while iOS's capture pipeline receives no frames. A later [camera
preview](https://www.reddit.com/r/hackios/comments/1xtcibu/camera_is_up/)
shows progression, but separate capture, pixel-format conversion, image
orientation, metadata, preview frame rate, still-photo save and multi-camera
support. No validated S20 driver source was found to reuse. A claim that
“camera works” is too coarse for a port case.

## 5. GPU: correctness, provenance and OS generation

- **Mali lineage:** S7 T880 and S9+ G72 demonstrate a practical **GLES via
  Mesa/Panfrost** fallback; an iOS view may work even with Metal incomplete.
  HakiOS MT6768's [Metal debugging plan](https://github.com/oosexgang/hakios-mt6768/blob/ad65e1f4b3ba479e9d7ada98f17398b83cc6f285/docs/metal-x6826b-plan.md)
  measures visual corruption under asynchronous rendering and a correct,
  slower synchronous configuration. This points to surface lifetime,
  fences, cross-frame writes and display ownership, **not** a general recipe
  to increase clocks until broken widgets disappear.
- **Pixel 5 Adreno lineage:** the [source-pinned README](https://github.com/maxexcloo/ios-redfin/blob/db05400e97fdcff14c2bfcb6a3ed18e0baa8187e/README.md)
  distinguishes direct scanout, CPU fallbacks and **scene-specific** delivered
  frames: a requested 90 Hz is not proof of 90 fps. Logs should pair frame
  latch timestamps with requested presentation and corruption checks.
- **Native iOS 27 Exynos:** Scion's [12 November S9 guide](https://github.com/Scion-Project/scion-kernel/blob/2a79ef85e4bf1fe17bc94e3d1db58ba1d78aa247/docs/ios27/INSTALL-S9.md)
  is notable for XNU 12377, iPhone 11 iOS 27.0.1 userland and **ARM feature
  differences** requiring AOT code rewrites. The guide **admits** the userland
  graphics overlay has not been built end-to-end from a fresh clone and some
  assets lack a public recipe; booting the kernel alone draws no SpringBoard.
- **MTK `viva` test suite:** [GPU README](https://github.com/Nik300/viva-gpu/blob/54011de06784d259d509d588839d2e739c6260c6/README.md)
  describes an explicit userspace/kernel interface, mocked rendering and
  pixel-diff testing on Mac. Preserve those *methods*; do not mark its actual
  phone's GPU as working until a phone run follows the mock tests.

**Critical G54 mismatch:** MT6855 Dimensity 7020 uses **Imagination IMG
BXM-8-256**, per [MediaTek's product page](https://www.mediatek.com/products/smartphones/mediatek-dimensity-7020),
**not Mali**. S7/S9/MT6768 Panfrost or PanVK cannot simply be enabled on the
G54. Mesa's [PowerVR driver support table](https://docs.mesa3d.org/drivers/powervr.html)
currently names active **BXM-4-64** and BXS-4-64 variants, **not BXM-8-256**.
Even products with identical marketing names can have different **BVNC** IDs.
Therefore a G54 GPU plan must first capture the device's exact GPU ID/BVNC,
kernel DRM/firmware stack, memory/IOMMU ABI and Mesa feature coverage. Any
PowerVR Vulkan→Metal bridge is **a research hypothesis**, not a working G54
driver. An offline Mesa `drm-shim`/shader-translation experiment is safer
than assuming a phone driver exists.

## 6. Hosted iOS is a legitimate but different research branch

[OneiOS README](https://github.com/akshaynexus/OneiOS/blob/c2d281a69b14915bc153c54b5120e30de7526a9d/README.md)
explicitly states that **One UI's Linux kernel keeps running**: XNU is
source-built as a process (`xnuhost`), iOS processes are hosted Linux
processes and host bridges expose GPU/touch/battery etc. The 11–12 November
author account records successful lock/Home screen sessions as well as
GPU regressions, a kernel collection mapping fault, missing icons, memory
pressure and failed return chord. A screenshot on a locked-bootloader S24
does not demonstrate that an Android phone can bypass verified boot and
direct-boot iOS. This project is much closer to *hosted compatibility* than
to the Nexus G54's independent XNU kernel boot path.

Potential portable **engineering practice**, not transplantable native
drivers: session ready/return contracts, hard recovery timers, host/guest
ownership of a buffer, first-boot vs warm-boot storage migrations, health
monitoring and reproducing GPU failures at a precise frame. Scion's Pixel
AVF and Asoft VM-style ports deserve their own `hosted` classification;
do not add them as physical XNU boot case successes.

## 7. Prioritized experiments for `g54-xnu` and Nexus

These are **proposals**, not authorised hardware actions. `g54-xnu` owns
phone code and tests; Nexus owns evidence schema, adapters once proven
reusable, and the cross-port learning. Each device operation remains under
the device owner's explicit approval/recovery rules.

| Priority | Concrete, bounded next task | Evidence needed before promotion |
| --- | --- | --- |
| 1 — radio inventory | Read stock MT6855 DT/driver/firmware metadata and compare with HakiOS MT6631 requirements; choose `same`, `different`, or `unknown` per interface | Chip ID, transport, per-register provenance, no writes |
| 2 — GPU feasibility | Confirm G54 BXM-8-256 **BVNC**, compare Mesa PowerVR tables/kernel, perform an **offline** shader+drm-shim proof if viable | GPU ID, source/driver revision, shader output diff, explicit missing hardware path |
| 3 — UI correctness benchmarks | Preserve current G54 SpringBoard/touch baseline; introduce deterministic screen scene/frame marker, count latched frames, test rotation/tearing and memory ownership | Run IDs, video/trace, actual canvas/refresh, before/after logs |
| 4 — staged peripheral contracts | Use BT six-HCI-command gate, Wi-Fi scan→association→IP→DNS→TCP, camera frame→preview→capture, battery readout→charging as **separate** milestones | One evidence record per observable transition; failing states kept |
| 5 — portable recipes | Extract **tests and interface descriptions** into Nexus only after another target demonstrates a stable shared boundary | Two targets, licences, source SHA, owner approval, offline validation |

Do not interrupt working physical G54 bring-up for unrelated source imports;
**read and compare first**. Prioritise the PowerVR feasibility gate over
the flashier S20/MT6768 Mali-GPU demos, because the actual silicon differs.

## 8. How future agents should extend this watch

For each claimed improvement, append or supersede a dated entry with:

1. Original post URL and date; exact device variant, SoC/GPU/radio and OS
   build; **direct XNU**, **hosted XNU**, **VM** or **UI imitation**.
2. Exact upstream commit/branch or “source not located”; identify whether
   code was only compiled, simulated on host, tested on device, or reproduced.
3. Minimal claimed milestone, **what the evidence actually shows**, and
   known failures (including first-boot vs reboot, missing services and
   whether claimed networking exchanges packets).
4. Portable interface or experiment, nonportable OEM IDs/firmware/ABI,
   licence/redistribution restrictions and potential confidential data.
5. A reversible offline test first. Only after a controlled hardware test
   and owner-reviewed artifact should a claim enter `docs/port-cases/` or
   elevate any `docs/status.md` target capability.

**Research boundary:** This watch inspects public code and original
developer reports; it does **not** validate screenshots against device
internals, examine private Telegram messages, execute upstream builds, or
reproduce the phone tests. Ongoing reports could supersede any observation.
