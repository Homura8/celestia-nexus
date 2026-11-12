# Development status — 12 November 2026

This is the durable handoff. Exact source revisions live in
[`upstreams.lock.toml`](../upstreams.lock.toml); experimental records are linked
below. Do not infer a later boot milestone from an earlier one.

## 1. What is verified

| Component | Status and evidence |
| --- | --- |
| CLI, immutable source cache, strict recipe inputs, command/error records | Implemented; 41 unit tests pass on Linux/Python 3.12.14 |
| HakiOS prebuilt XNU in stock QEMU/AArch64 | Locally booted; exact kernel SHA pinned, source correspondence unverified |
| Placeholder UEFI loader | Built from pinned source with LLVM 19; boot-tested; separately hashed upstream prebuilt also boot-tested |
| Original SDK-free Darwin userspace probe | Source-built; all ten checks pass, fresh token returned, two heartbeats observed, no panic |
| Final instruction-clock baseline | Four fresh boots: two source loaders, two prebuilts; 4.663 / 3.354 / 3.679 / 2.720 seconds; clean QMP exit 0 |
| Repeated source build | Kernel, probe and source-loader hashes identical on the same host/toolchain; no cross-host bit-for-bit claim |
| Failure/interrupt handling | Real 0.1-second run times out with CLI exit 1; real SIGINT returns 130; both stop QEMU cleanly and retain records |
| Kernel source preparation | Exact Apple XNU/HFS + both patch series + QEMU driver configuration; diff check passes; 5,188 files hashed, 4 of 25 selectable drivers enabled |
| CI configuration | Read-only permissions, pinned actions, Linux/macOS Python matrix, asset-free real QEMU/source-preparation job; remote result must be checked separately |

Reference environment: Debian 13 x86_64, Python 3.12.14, Clang/LLD 19.1.7,
QEMU 10.0.13, AAVMF 2025.02. The local tools were extracted from signed Debian
packages into a user-writable prefix. No proprietary Apple asset was used.

Reproduce:

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

- **Not a complete iOS/Darwin distribution:** no stock Apple launchd, dyld,
  SpringBoard, GUI, App Store, networking, audio, GPU or physical-device boot
  has been implemented/reproduced by Nexus. Upstream reports are in research.
- **Kernel not rebuilt here:** source assembly passed, but the full kernel
  SDK/toolchain dependency path is unverified. The pinned kernel banner says
  it came from a dirty source tree; its hash does not prove exact source identity.
- **Host coverage:** local real boots are Linux x86_64/LLVM 19/QEMU 10. macOS
  execution paths and other versions require their own results. HVF/KVM is not
  implemented by this recipe. Guest instruction-clock time is not host timing.
- **One unexplained host-clock UEFI stall:** an optional prebuilt-loader trial
  timed out before loader entry. QMP/registers were saved. Six diagnostic cold
  replays succeeded; changing disk boot order did not establish a fix. Default
  icount has four passing acceptance boots, but is not proof that the underlying
  host-clock issue is repaired. No retry hides failures.
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

## 4. Prioritised next work

1. **Reproduce ios-qemu's iOS 16.7.16 userland path on a suitable Mac.** It is
   already more advanced than a kernel demo. Review/pin the kernel build and
   user-supplied IPSW, use a disposable disk, preserve its upstream harness and
   add independently checked launchd/SpringBoard/app milestones. Required human
   inputs are an authorised OS source and execution on the appropriate host.
2. **Rebuild and boot source XNU with an authorised SDK/toolchain.** Start from
   the prepared tree, inventory all dependencies, capture compile/link failures,
   and pass the resulting kernel to `build --kernel`. Establish actual source
   correspondence before proposing a binary release.
3. **Investigate the host-clock UEFI stall and expand host coverage.** Compare
   exact QEMU/AAVMF versions and capture firmware state at the stuck PC; validate
   current CI and an Apple Silicon host. Do not relax the acceptance checks.
4. **Reproduce UniXNU's common UEFI/native-user QEMU path as a second recipe.**
   This tests reuse across genuinely different boot contracts. Share only the
   mechanics both implementations exercise; retain component/port ownership.
5. **Begin a real device feasibility record**, potentially Moto G54 5G, after
   confirming the exact variant, CPU/boot constraints and available upstream
   support. No device unlock/flash instructions or support claims are prefilled.

Owner review: the PR proposes MIT for original Nexus code. No extra credentials
or physical-device action is required for the open baseline. Do not supply Apple
account credentials, firmware keys or OS files through a public issue/PR.
