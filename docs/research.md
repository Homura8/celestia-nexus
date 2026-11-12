# Ecosystem research — 12 November 2026

Exact reviewed revisions and licences are machine-readable in
[`upstreams.lock.toml`](../upstreams.lock.toml). Links below point at those
snapshots rather than a moving branch. **Source-inspected** means code/build
paths were examined. **Upstream-reported** means a maintainer describes the
result; it is not an independent reproduction by Nexus. The locally reproduced
results are in [`status.md`](status.md) and its linked raw evidence.

## 1. Comparison and initial choice

| Approach | Strongest relevant upstream report | Assets/host coupling | Nexus decision |
| --- | --- | --- | --- |
| HakiOS source XNU + own UEFI/platform drivers | iOS 16.5 userland on generic QEMU and Qualcomm phones; open syscall-userspace path | Open boot needs only QEMU/LLVM/UEFI; kernel rebuild still needs SDK/toolchain material | Reproduce open path first; locally verified |
| ios-qemu source XNU + generic QEMU devices | iPhone X iOS 16.7.16 GUI, input, sound and networking on Apple Silicon | HVF-centric full-userland harness, writable HFS+/UFS disk, Apple OS/SDK inputs | Highest-priority stock-iOS reproduction candidate; source-inspected only |
| UniXNU UEFI environment + reusable platform/OS components | Broad non-Apple ARM64 porting infrastructure; independent QEMU port reports iPadOS 17 GUI/Metal remoting | OS profiles, prelinking and original Apple kext/userland assets; device port ownership separate | Reuse its implementation boundary in a later recipe; do not recreate its driver/feed system |
| darwin-vm + qemu-sptm | Recent iOS/macOS CLI root shell with SPTM/TXM/Apple CPU support | Custom QEMU, original kernel/firmware/ramdisk; macOS preparation | Strong alternative for stock-kernel research, not proof of native-device support |
| Aleph xnu-qemu-arm64 | iOS 12.1 shell, debugging, storage/UART networking and KVM | Old device-emulation/QEMU branch, kernel patches and Apple assets | Historical provenance/debug reference, not the new baseline |
| Inferno | Apple ARM device emulation; ecosystem demonstrates iOS 14 paths | Larger device-specific emulator and proprietary inputs; distinct copyleft terms | Research alternative; no code incorporated |

The open milestone is intentionally not the ecosystem's most advanced result.
It is the most directly reproducible endpoint available here without Apple
proprietary assets, and it runs quickly on an x86 Linux host. No original IPSW
or authorised SDK was supplied. The next step is to reproduce the advanced
userland paths, not to build an inferior parallel driver ecosystem indefinitely.

## 2. HakiOS: reproduced generic-hardware XNU path

Canonical common repository:
[`oosexgang/hakios-xnu-kernel`](https://github.com/oosexgang/hakios-xnu-kernel/tree/63fc2b4633bac3af8e57dadab9f5a8d4cb940438).
Its README identifies separate device/SoC/UEFI repositories and marks the old
userland repository as a pointer. Search also finds `hakios-os` names and
`enesuzun2002/hakios-apollo`; do not silently use those as the canonical common
tree. The checked common commit is dated 6 November 2026; active documentation
and a current README alone do not establish every feature's correctness.

Inspected implementation:

- [`Makefile`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/Makefile)
  has `qemu-open`, building kernel, placeholder loader and a static raw-syscall
  program. `qemu/run.sh` uses stock `virt`, GICv3, Cortex-A76, TCG, one CPU,
  pflash firmware, an ESP and an XNUP payload at `0xF0000000`.
- [`xnuloader/loader.c`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/xnuloader/loader.c)
  loads ARM64 Mach-O segments, chooses RAM, creates an Apple-format device tree
  and `boot_args`, exits UEFI boot services, disables the MMU and enters XNU.
  The fixed XNUP header/entries are a private interoperability contract, not a
  universal firmware interface. `mkidentity.py --placeholder` needs no IPSW.
- [`gic_v3_irq.c`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/xnu/files/osfmk/arm64/gic_v3_irq.c)
  provides the missing generic interrupt controller interface, including virtual
  timer PPI 27 and IPIs. `GenericARMPE.cpp`, PSCI support, the MMU/page changes
  and mockfs patches are substantive platform work; standard QEMU alone cannot
  boot arbitrary stock iOS kernels with these generic devices.
- `drivers/` separates common VirtIO and device-oriented drivers; `drivers/map`
  and `tools/hakios-config.py` select files/options. QEMU's defconfig excludes
  phone-specific drivers. The shipped prebuilt was built earlier and is not
  asserted to be that exact configuration.
- [`xnu/apply.sh`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/xnu/apply.sh)
  pins XNU 8796.121.2 at `c54f35c…`; `xnu/hfs/hfs.sh` pins HFS 627.100.6 at
  `31d5ec2…`. Source assembly overlays a patch, new files, HFS sources/patches
  and drivers, then generates XNU build configuration. Nexus reproduces these
  source transformations, with exact commit checks and a file-hash manifest.
- `xnu-deps/setup.sh`, `xnu-env.sh` and `tools/make-kernel.sh` reveal the real
  rebuild prerequisites: Theos/cctools, MIG, SDKs, firehose/libpthread support
  and known final symbol-set failures. The latter script classifies those
  failures; an ignored nonzero build exit must not masquerade as a fresh kernel.
  Nexus does not automatically run the SDK-download/setup path.

**Observed locally:** the hashed prebuilt kernel and loader reached userspace.
The bundled prebuilt hello printed PID 1 then exited/panicked even with
`hello_wait=120`; current `hello.c` has features absent from that prebuilt.
Nexus's original probe instead tests kernel behaviour and stays alive. Both the
source-built placeholder loader and separately pinned prebuilt loader are tested
through the same boot checks; see the evidence record for final results.

**Provenance limit:** `prebuilt/SHA256SUMS` says built 25 October and the kernel
banner describes a dirty source tree. A matching binary SHA establishes which
binary ran, not correspondence to the later source commit. A source rebuild
and comparison remain necessary. `THIRD_PARTY_LICENSES.md` explicitly marks
several non-QEMU firmware/graphics items uncertain. No fetched tree or binary
is republished by Nexus, and no blanket licensing clearance is asserted.

Reproduction: `./nexus smoke`; source assembly: `./nexus prepare-kernel`.
These replace an unbounded manual experiment with saved inputs, commands,
failure classification and executable acceptance criteria.

## 3. ios-qemu: direct candidate for iOS 16.7.16

Reviewed:
[`lgrachov/ios-qemu`](https://github.com/lgrachov/ios-qemu/tree/8d23f48c683250c728a5c820482b450646453c02).
README credits dipa-studio/Lev and the original `sweet` phone work. Some internal
documentation still points at `dipa-studio/ios-sweet` CI artifacts; the reviewed
snapshot is the explicit source of truth, not those stale commands. Its latest
checked commit is dated 25 October 2026.

[`harness.sh`](https://github.com/lgrachov/ios-qemu/blob/8d23f48c683250c728a5c820482b450646453c02/harness.sh)
generates an Apple device tree and kernel/boot-argument payload, then calls
`tools/qemu-sweet.py`. Unlike HakiOS's UEFI path, its small AArch64 boot stub
initialises ramfb/storage and jumps directly into XNU. `--ios` implies HVF,
high-memory layout, an emulated UFS disk and userland boot arguments. Input,
network and sound use built-in generic VirtIO-facing kernel implementations;
graphics primarily use software rendering, with experimental host Metal work.

[`xnu.yml`](https://github.com/lgrachov/ios-qemu/blob/8d23f48c683250c728a5c820482b450646453c02/.github/workflows/xnu.yml)
uses macOS 14/Xcode 15-era `iig`, a pinned
[`blacktop/darwin-xnu-build`](https://github.com/blacktop/darwin-xnu-build/tree/663906528d1cd5ea8fde7de6f16de73db9511549)
commit and its own patch series, targeting XNU 8796/SWEET. The Xcode choice is
an IORPC ABI requirement, not arbitrary host preference. Root-image builders
need the user's own iPhone X 16.7.16 filesystem and make writable HFS+ images.

Integration caveat discovered during CI validation: GitHub
[retired its macOS 14 runners on 2 November 2026](https://github.blog/changelog/2026-10-01-github-actions-macos-14-runner-image-retirement/).
The pinned upstream's `macos-14` workflow cannot be reused unchanged on GitHub's
current hosted runners. Preserve its Xcode/iig ABI requirement using an
appropriate authorised build host, or validate an actual toolchain adaptation.
Nexus's own SDK-free Python CI uses the supported `macos-26` image.

**Upstream-reported:** lock/home screens, stock apps, Safari networking and
sound on an Apple Silicon Mac. **Not reproduced here:** any stock iOS userland,
full kernel rebuild, networking, sound or GUI. We inspected the boot/build
implementation and did not infer support for Linux TCG full userland from its
HVF result. MIT tools and APSL XNU modifications retain distinct obligations.

Next reproduction, on a suitable Mac with authorised inputs: build/download an
exact attributable kernel, prepare a disposable copy of the user's OS disk,
then run the pinned harness's documented `--kernel … --ios …` path. A Nexus
recipe should preserve logs and distinguish launchd/SpringBoard/usable-app
evidence. It must not modify an original supplied disk silently.

Linux/cloud note (source-inspected, **not reproduced**): `--ios` forces HVF
([`harness.sh`](https://github.com/lgrachov/ios-qemu/blob/8d23f48c683250c728a5c820482b450646453c02/harness.sh#L52)), but the same kernel also boots under TCG,
and the maintainer's notes compare TCG and HVF kernel timings
([`NOTES.md`](https://github.com/lgrachov/ios-qemu/blob/8d23f48c683250c728a5c820482b450646453c02/NOTES.md#L214)). A Linux root-disk builder using `apfs-fuse`
also exists ([`tools/mkiosroot.sh`](https://github.com/lgrachov/ios-qemu/blob/8d23f48c683250c728a5c820482b450646453c02/tools/mkiosroot.sh)). So whether iOS
16.7.16 userland reaches SpringBoard on Linux TCG (or Linux/arm64 KVM) is an
open, cheap-to-try question for cloud agents: expect it to be much slower, and
the kernel still has to be built on macOS (Xcode `iig` requirement above).

## 4. UniXNU and independent QEMU ports

Reviewed common tree:
[`UniXNU/UniXNU`](https://github.com/UniXNU/UniXNU/tree/c34f018aafd6befd5dc93c05a8dccd5bdce6724b),
dated 12 November 2026; independent device tree:
[`xVanTuring/UniXNU-qemu`](https://github.com/xVanTuring/UniXNU-qemu/tree/97b75b1f63c6b7e895cd7646029db741d5fe5488).
The [official QEMU device page](https://unixnu.com/devices/qemu) explicitly says
community ports have independent maintainers. A common-project listing does
not transfer maintenance ownership or prove a local reproduction.

Inspected `scripts/unixnu/{feeds,profiles,kernel,pipeline}.py`, `.gitmodules`,
`docs/reference/qemu.md`, OS/architecture profiles, the device's `board.toml`,
`feeds.toml` and `scripts/run-qemu.py`:

- Common UEFI environment and DarwinBoot/platform components are separate from
  SoC/device repositories. Feeds support local overrides, exact source locks
  and component provenance. Existing machinery is a stronger reuse candidate
  than a new Nexus plugin or driver framework.
- The kernel pipeline can build source XNU and prelink selected original Apple
  kernel components. OS profiles cover distinct versions; 4 KiB user ABI,
  signature-page, bootstrap and filesystem patches are concrete compatibility
  work, not interchangeable feature flags across arbitrary releases.
- Common UEFI smoke scenarios exercise menu/input/driver/initrd handoff without
  claiming an OS boot. The independent QEMU runner additionally stages
  DarwinBoot, Apple-format DT/owned-memory windows, mockfs native-user fixtures,
  verified VirtIO OS roots, SystemOS/Data images and framebuffers.
- The inspected device pins iPadOS 17.7.11/21H461 and specific OS image/trust-cache
  hashes; its root and `--metal` paths require more than just compiling UEFI.
  Host Metal remoting is not a native phone GPU driver or portable Linux GPU.

**Upstream-reported:** iPadOS 17 home screen and Settings, with documented
limitations and host-Metal requirements. **Nexus:** source-inspected only; no
UniXNU firmware/OS/GUI execution claimed. Core licence is BSD-2-Clause-Patent;
each external component/Apple input retains its own terms.

A later integration should reproduce the common UEFI smoke/native-user path
and then the independent device's exact OS profile. Keep that device's
configuration/ownership intact rather than importing its entire stack into
Nexus or treating its reports as framework-wide support.

## 5. Stock-kernel emulation alternatives and original provenance

[`jprx/darwin-vm`](https://github.com/jprx/darwin-vm/tree/edfc19433da8d04d5927a7b1932acce4034f307c)
pins qemu-sptm at `bad6336…`. Inspected `get_files.sh`, `run.sh`, `.gitmodules`,
`qemu-sptm/hw/arm/{darwin,xnuboot_sptm,xnu_patch}.c` and the README. `run.sh`
passes original BootKC, DT, trust cache and ramdisk to a `darwin` machine, with
optional SPTM/TXM. The loader composes the SPTM/TXM/kernel memory layout; CPU
emulation implements Apple-specific protections/features. Asset preparation
uses macOS image mounting/signing and ownership changes. The author explicitly
targets a CLI root shell, not a complete GUI/device emulator. This is a strong
way to study current stock kernels, but its result says nothing about native
Android-device drivers. It was not run here. MIT harness/QEMU licences differ.

[`alephsecurity/xnu-qemu-arm64`](https://github.com/alephsecurity/xnu-qemu-arm64/tree/2694993f9281a8678d519704c3cd29d4c9d39415)
is an older QEMU fork. `hw/arm/n66_iphone6splus.c`, XNU trampoline, DT/memory
helpers and the referenced
[2019 author's tutorial](https://alephsecurity.com/2019/06/17/xnu-qemu-arm64-1/)
trace the iOS 12 shell and later KVM/debug/UART-network work to its original
research. The inspected head is dated September 2021 despite the README's
“active development” text. No current-maintenance claim or local reproduction
is inferred. Its device-emulation/kernel patch assumptions should not define
Nexus's generic-hardware architecture.

[`ChefKissInc/Inferno`](https://github.com/ChefKissInc/Inferno/tree/cc4302a99167abec69b714cfd00c38caece7e7de)
is the current reviewed project name rather than an arbitrary QEMUAppleSilicon
mirror. Inspected `hw/arm/apple-silicon/t8030.c`, boot/kernel-patch code and Apple
AIC/SEP device structure. This emulates Apple hardware rather than replacing
its drivers with generic platform implementations. The README distinguishes
GPL-3.0, AGPL-3.0 original additions and retained per-file QEMU terms; copying
code into MIT Nexus would require specific compatibility review. No code was
copied, built or run here.

## 6. Findings from implementation

| Experiment | Observation | Consequence |
| --- | --- | --- |
| Bundled HakiOS prebuilt hello | PID 1 ran, then exited/panicked; current-source wait option absent | Use an original persistent probe; require liveness after a result |
| LLVM 19 Mach-O static linking | `-static` is unimplemented; normal output requests dyld | Build a no-library probe and validate/convert its own static entry; test bounds |
| QMP UNIX socket in this execution sandbox | `Operation not permitted` before any loader output | Use inherited stdio pipes; no socket permission or management port required |
| Pinned source-built loader + original probe | Ten checks and continued userspace execution; clean QMP shutdown | First executable regression baseline established |
| Real XNU/HFS patch assembly | Both patch checks/applications and QEMU driver generation succeeded | Prepared source tree is usable for the next kernel-build session |
| Full kernel rebuild / original userland | Authorised SDK and OS materials were not supplied | Record as unverified; keep the open baseline and explicit asset-dependent next steps |

One later host-clock/prebuilt-loader cold boot stalled in UEFI before any loader
banner; QMP still reported a running CPU. Six follow-ups (three original boot
settings, three with an explicit disk boot order) all reached the probe in about
eight seconds. Boot order did not establish a fix, and the cause remains open.
The failing serial log/registers and the follow-up summary are retained.

A separate experiment with fixed instruction-count time passed in about three
seconds, including the guest timer test and two heartbeats. QEMU's
[icount implementation](https://www.qemu.org/docs/master/devel/tcg-icount.html)
explains its virtual-instruction clock and lack of cycle-accurate timing; the
`sleep=off` timer-warp behaviour was also checked in the official v8.2.2 and
v10.0.3 `accel/tcg/icount-common.c` source. This is a deliberate test-environment
choice, not a claim that the unreproduced firmware stall's cause was repaired.

Remote CI then exposed a version constraint missed by the initial local tests:
Ubuntu's QEMU 8.2.2/AAVMF 2024.02 froze before loader entry, including QMP. The
exact distribution binaries/firmware were brought into the local prefix for a
controlled comparison. QEMU 8.2 failed in instruction mode with both AAVMF 2024
and 2025, and with both a real FAT image and vvfat; QEMU 10 passed with the older
firmware. On QEMU 8.2, removing only icount passed the same guest in 9.618 seconds.
The default therefore remains the broadly compatible ordinary clock. The optional
fast clock is explicitly gated to QEMU 10+; 9.x is unvalidated, not claimed broken.
No extra filesystem builder/dependency or automatic retry was added. This
version-specific icount failure is distinct from the earlier sporadic host-clock
UEFI stall. See the portable-validation and CI evidence added alongside the fix.

Future updates should change the lock, inspect changed implementation/licences,
run the affected real experiments and update status with evidence. A newer
README, screenshot, release label or success-shaped log is not enough.

## 7. Existing device ports and phone workflows

Added by the PR #1 review, 12 November 2026. Before starting any device port,
check whether one already exists. Both projects below are full porting
frameworks; Nexus should orchestrate and record them, not duplicate them.

**UniXNU device registry** ([`devices.toml`](https://github.com/UniXNU/UniXNU/blob/2bbb39dcee0cada3b04e41f0256d678e80667c5b/devices.toml), inspected at
`2bbb39d`, later the same day as the lock pin): 355 community device records.
142 are marked `available`, 39 `invalid`, 17 `missing` and the rest carry no
state. Most are Qualcomm Snapdragon (SM8550 alone has 83), with 13
MediaTek records (MT67xx/MT68xx/MT69xx, MT8167) and a few Exynos, Tensor,
Unisoc and RK3588 entries. Eleven records use an `ios-16.7.16-20H392` OS
profile; their summaries show varied maturity (for example "Darwin 22 ABI and
firmware pending"), and a record is a maintainer's report, not a reproduction.
UniXNU's [bring-up guide](https://github.com/UniXNU/UniXNU/blob/2bbb39dcee0cada3b04e41f0256d678e80667c5b/docs/porting/bring-up.md) proceeds in staged,
observable checkpoints from `fastboot boot` of the UEFI image to the OS.

**HakiOS phone tooling** (same commit as the lock):

- [`xl`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/xl) drives a phone over the fastboot protocol: it enters a resident
  loader, uploads and runs a kernel **from RAM** (nothing flashed by default),
  fetches logs during and after the run, has a watchdog/stop path, locks the
  phone against concurrent runs and returns it to Android.
- [`tools/hakios-device.py`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/tools/hakios-device.py) `new --fdt` scaffolds a
  device repository from the phone's own device tree, and
  [`docs/porting/index.md`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/docs/porting/index.md) orders driver bring-up
  with a "done when" check per step. That guide assumes an ARM64 Qualcomm SoC
  with a UEFI port; the README lists a separate experimental MediaTek Helio G85
  (MT6768) port with its own loader.
- [`devices/manifest.conf`](https://github.com/oosexgang/hakios-xnu-kernel/blob/63fc2b4633bac3af8e57dadab9f5a8d4cb940438/devices/manifest.conf) lists HakiOS's device,
  SoC and UEFI repositories at pinned revisions.

ios-qemu itself grew out of `sweet` (Redmi Note 10 Pro) phone work; the same
phone also has a separate UniXNU community record. UniXNU's registry is the
broadest shared index of device ports found in this review.

**Consequence for Nexus:** "Port iOS X to device Y" starts by looking Y and its
SoC up in these registries ([porting](porting.md#1-look-for-an-existing-port)). A
future physical-device recipe should wrap an upstream workflow such as `xl` or
UniXNU's `fastboot boot` stages, behind explicit owner authorisation, and record
its logs with the same evidence rules. None of this was executed here.
