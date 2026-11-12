# Development status — 12 November 2026 (ios-qemu milestone)

This is the durable handoff. Exact source revisions live in
[`upstreams.lock.toml`](../upstreams.lock.toml); experimental records are linked
below. Do not infer a later boot milestone from an earlier one.

## 1. What is verified

| Component | Status and evidence |
| --- | --- |
| **Stock iOS 16.7.16 userland (recipe `ios-qemu`, second milestone)** | **Reproduced on an M1 Pro / macOS 27.2.1 / QEMU 11.1.3 (HVF)** from the user's own iPhone X IPSW: kernel → UFS root → launchd → SpringBoard + backboardd → lock screen → injected unlock → home screen → injected tap starts Safari. Fresh-disk run 128 s, all seven milestones ([evidence](evidence/2026-11-12-ios-qemu/README.md), [guide](ios-qemu.md)) |
| iOS disk preparation | `prepare-disk`: IPSW manifest + SHA-256, LZFSE device tree decoded with macOS libcompression, upstream `mkiosroot-mac.sh` under one `sudo`; about 5 min |
| Recipe-declared CLI | Second recipe moved the first recipe's CLI/QEMU assumptions into `hakios.py`; commands, options and build records are per recipe |
| Bounded process lifecycle | Ctrl-C/SIGTERM/SIGHUP/timeout stop the guest in timed steps (QMP `quit` 0.1–0.2 s); a wedged QEMU is detected after 30 s and killed by exact pid in 3 s; verified against real QEMU and fake processes |
| CLI, immutable source cache, strict recipe inputs, command/error records | Implemented; 75 unit tests pass on Python 3.15.2 (48 before this milestone) |
| Independent review reproduction | Fresh Ubuntu 24.04 container, Ubuntu QEMU 8.2.2/AAVMF 2024.02: 39 real boots, 38 passed, 1 firmware stall ([evidence](evidence/2026-11-12-review/README.md)); then a fresh-workspace `smoke` with each loader and `prepare-kernel` from the canonical GitHub URLs, all passed |
| Source mirrors (`NEXUS_MIRROR_<ID>`) | Implemented and unit-tested; used for the review's real HakiOS fetch, recorded in `operation.json` |
| HakiOS prebuilt XNU in stock QEMU/AArch64 | Locally booted; exact kernel SHA pinned, source correspondence unverified |
| Placeholder UEFI loader | Built from pinned source with LLVM 19; boot-tested; separately hashed upstream prebuilt also boot-tested |
| Original SDK-free Darwin userspace probe | Source-built; all ten checks pass, fresh token returned, two heartbeats observed, no panic |
| Portable default baseline | Fresh ordinary-clock boots with QEMU 8.2 source/prebuilt loaders (9.455 / 9.573 s) and QEMU 10 source loader (9.533 s); clean QMP exit 0 |
| Optional instruction-clock baseline | QEMU 10: four earlier fresh boots with both loaders, plus a final source-loader pass in 2.748 s; all ten checks and clean shutdown |
| Repeated source build | Kernel, probe and source-loader hashes identical on the same host/toolchain; no cross-host bit-for-bit claim |
| Failure/interrupt handling | Real 0.1-second run times out with CLI exit 1; real SIGINT returns 130; both stop QEMU cleanly and retain records |
| Kernel source preparation | Exact Apple XNU/HFS + both patch series + QEMU driver configuration; diff check passes; 5,188 files hashed, 4 of 25 selectable drivers enabled |
| CI configuration | Read-only permissions, pinned actions, Linux/macOS Python matrix, asset-free real QEMU boots on Ubuntu and macOS plus source preparation; [run on `5a2f4c0`](https://github.com/Homura8/celestia-nexus/actions/runs/43179600704) passed all six jobs |
| macOS host | Real boot in CI on macOS 26.7.2/Apple Silicon with the README's Homebrew tools: QEMU 11.1.3, Homebrew EDK2 firmware, clang/LLD 23.1.4; all ten checks, two heartbeats, about 13 s. TCG only, not HVF |

Reference environment: Debian 13 x86_64, Python 3.12.14, Clang/LLD 19.1.7,
QEMU 10.0.13, AAVMF 2025.02. The local tools were extracted from signed Debian
packages into a user-writable prefix. The portable comparison also ran Ubuntu's
QEMU 8.2.2/AAVMF 2024.02 binaries in that prefix, with downloaded package hashes
checked against the official archive where applicable. That comparison is not
an Ubuntu-host claim; remote CI covers the actual Ubuntu host. No proprietary
Apple asset was used.

Reproduce the open baseline (the iOS recipe's commands are in [ios-qemu.md](ios-qemu.md)):

```sh
./nexus doctor
./nexus smoke
./nexus smoke --loader prebuilt
./nexus prepare-kernel
python3 -m unittest discover -s tests -v
```

Raw logs, exact command lines, firmware/tool/input hashes, QMP registers and the
validation summary are in [`evidence/2026-11-12`](evidence/2026-11-12/README.md).
These are real guest results; unit/protocol fixtures are labelled separately.
The probe validates console, PID 1, UID 0, sysctl, boot-token transport, syscall
error reporting, memory mapping/readback, mprotect, munmap and guest timer delay.

## 2. Limits and unresolved findings

- **iOS is a research environment, not a device:** the ios-qemu recipe runs
  stock launchd, SpringBoard and Safari, but with no GPU (software rendering),
  Secure Enclave, baseband or code-signing security; poster/wallpaper
  extensions and driverkitd crash-loop (upstream's known blue-wallpaper
  limit). Web browsing, sound, App Store and long-running stability were not
  checked. No physical-device boot has been attempted.
- **ios-qemu host coverage:** one M1 Pro, macOS 27.2.1, QEMU 11.1.3. Upstream
  reports an M5/macOS 26/QEMU 11.0.2. Linux/TCG and Intel Macs are not
  validated and the recipe refuses non-HVF settings.
- **ios-qemu kernel provenance:** upstream's CI artifact, matched to the pinned
  patch series by Git object IDs; not rebuilt. GitHub deletes it on
  **2027-01-23**; keep `.nexus/downloads/` or rebuild (needs Xcode 15 `iig`).
- **QMP virtual-memory reads freeze QEMU on this HVF host** (root cause not
  established). Nexus avoids them; upstream's own `--live-log` triggers it here.
- **Guest network egress:** the guest's user-mode NAT contacts Apple and other
  servers as daemons start; upstream's launcher cannot disable it.
- **Kernel not rebuilt here:** source assembly passed, but the full kernel
  SDK/toolchain dependency path is unverified. The pinned kernel banner says
  it came from a dirty source tree; its hash does not prove exact source identity.
- **Host coverage:** real boots on Linux x86_64 (LLVM 18/19, QEMU 8.2 and 10) and
  in CI on macOS/Apple Silicon (LLVM 23, QEMU 11). Other hosts and versions,
  including Linux/arm64, require their own results. HVF/KVM is not
  implemented by this recipe. Guest instruction-clock time is not host timing.
- **Intermittent UEFI stall before the loader, cause unknown:** seen twice, on
  QEMU 10.0.13/AAVMF 2025.02 (prebuilt loader) and on QEMU 8.2.2/AAVMF 2024.02
  (source loader). Firmware prints its banner and clears the screen, then the
  vCPU keeps running inside firmware without reaching the loader. Both
  occurrences were inside a `smoke`; the review's happened on the first QEMU
  launch in a freshly provisioned VM. 38 later review boots and six earlier
  replays passed, so it is rare and not yet reproducible on demand. Runs now
  diagnose it specifically and record `stage_seconds` (the loader normally
  appears after about 7 s); rerun `./nexus run` with the same build. A CI job
  can hit it too: re-run the job and keep the failed artifact. No automatic
  retry hides failures.
- **Licensing:** no upstream source/binary is redistributed. HakiOS records
  unresolved non-QEMU third-party provenance; source preparation does not clear
  those files or a resulting kernel for redistribution.

## 3. Expensive findings already resolved

| Attempt | What happened / what to retain |
| --- | --- |
| Upstream prebuilt hello | Reached PID 1 then exited/panicked; current-source `hello_wait` is absent from that prebuilt. Replaced with a persistent original probe. |
| LLVM 19 `-static` | Unsupported Mach-O linker option. A bounded, tested conversion supplies a static thread entry for the original no-library probe. |
| QMP UNIX socket | This sandbox refused socket creation before boot. Pipes solved the management transport without opening a port. |
| Kernel source patch assembly | Exact XNU/HFS patches, overlays and QEMU configuration succeeded; use `prepare-kernel` instead of reconstructing the sequence. |
| Host-clock firmware stall | Cause unresolved; retain the failing evidence and six follow-ups instead of declaring it fixed or repeating blind retries. |
| QEMU 8.2 instruction-clock CI freeze | Reproduced with both firmware/media variants; ordinary clock boots the same inputs. Host clock is default; doctor rejects the optional fast clock below QEMU 10. |
| ios-qemu `--live-log` under HVF (M1 Pro, QEMU 11.1.3) | QMP `memsave` of kernel VAs froze QEMU's main loop; reproduced on demand. Read physical memory only (symbol table + page walk) |
| ios-qemu boot-arg token | The kernel never prints boot-args; freshness comes from reading live guest RAM instead |
| Upstream README Safari coordinate | (561, 2259) misses the default 4-icon dock; use (433, 2267) |
| Shutdown through upstream's launcher | Its SIGTERM path runs `info registers` (needs a vCPU); stop QEMU with QMP `quit`/exact-pid signals first |

## 4. Prioritised next work

Item 1 of the PR #1 list (reproduce ios-qemu's iOS 16.7.16 userland) is done
to the interaction milestone above. Next, in order:

1. **Secure the ios-qemu kernel before 2027-01-23.** The same XNU 8796
   lineage now demonstrably builds on GitHub's current `macos-15` runner with
   Xcode 16.0 and no KDK (g54-xnu K0, [research §8](research.md#8-mediatek-phones-direct-lk--xnu-ios-16-versus-unixnu-ipados-17)).
   Try ios-qemu's own patch series the same way and compare its exec-data
   hash with the pinned kernel (untested; ios-qemu's workflow targets Xcode 15).
   A rebuild is also the first step towards source correspondence.
2. **Report/minimise the HVF QMP freeze.** Reduce it to stock QEMU + a tiny
   guest (`x` of a VA while vCPUs spin) on M1 + macOS 27 and report to QEMU;
   compare QEMU 11.0.2 (upstream's version) to isolate a regression.
3. **Deepen the ios-qemu milestones without adding flakiness:** offline
   network option (needs a launcher change upstream or a Nexus launcher),
   a page load in Safari against a local server, Settings → About showing
   the synthetic identity, and a 1-hour soak with crash counts.
4. **Time-box a Linux/TCG attempt** of the same kernel and disk for cloud
   agents ([research §3](research.md#3-ios-qemu-direct-candidate-for-ios-16716)); the disk must be
   built on macOS today. Expect it to be slow; record where it stops.
5. **First physical-device consumer: the independent
   [`Homura8/g54-xnu`](https://github.com/Homura8/g54-xnu) port.** The registry
   search found no MT6855/G54 port; the closest proven path is ruby-ios-bringup's
   direct LK → XNU 8796 + iOS 16.7.16 on MT6877 ([research §8](research.md#8-mediatek-phones-direct-lk--xnu-ios-16-versus-unixnu-ipados-17)).
   The G54 repository owns all device code; Nexus gains code only when a
   second device would reuse it (candidates once real use appears: verifying
   CI-built kernels by segment hash, letting an external repository pin its
   own sources, a RAM-only device-run record). No flashing without approval.
6. **Intermittent HakiOS UEFI stall** and broader host coverage (unchanged).
7. **External device repositories pinning their own sources** once one exists.

Owner review: the PR proposes MIT for original Nexus code. No extra credentials
or physical-device action is required for the open baseline. Do not supply Apple
account credentials, firmware keys or OS files through a public issue/PR.
