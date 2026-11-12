# Development and reproduction

## Host setup

The reference host is Debian 13, x86_64, Python 3.12.14, LLVM 19.1.7,
QEMU 10.0.13 and Debian AAVMF 2025.02. Its real boot evidence is under
[`evidence/2026-11-12`](evidence/2026-11-12/README.md). Internet is needed for the
first pinned source fetch; build/run then work offline. Python has no pip dependencies.

Debian 13:

```sh
sudo apt-get install python3 git qemu-system-arm qemu-efi-aarch64 clang-19 lld-19
./nexus doctor
./nexus smoke
```

Ubuntu 24.04's package names are `python3 git qemu-system-arm qemu-efi-aarch64
clang-18 lld-18`. CI exercises this version combination; do not assume it has
passed until the relevant workflow result is green. On macOS, `brew install
python qemu llvm lld` and put `$(brew --prefix llvm)/bin` first on `PATH`.
Homebrew ships LLD (`ld64.lld`, `lld-link`) as its own formula, separate from
`llvm`, and Apple's default linker is not `ld64.lld`. CI boots the baseline on
macOS 26/Apple Silicon with exactly these Homebrew packages (TCG, not HVF).

No root privileges are required by Nexus. System package installation is a
separate host action; restricted environments can extract signed distribution
packages into a local prefix and provide tool paths. The reference session used
this approach, without changing system packages. Firmware and its variables
template must both be 64 MiB, from the same non-Secure-Boot AArch64 firmware
package. Secure-Boot firmware will reject the research loader.

Overrides (paths to individual executables, not shell command strings):

| Variable | Meaning |
| --- | --- |
| `NEXUS_QEMU` | `qemu-system-aarch64` |
| `NEXUS_CLANG` | Clang with AArch64 Mach-O and COFF backends |
| `NEXUS_LD64` | `ld64.lld`, the Mach-O linker |
| `NEXUS_LLD_LINK` | `lld-link`, the COFF/PE linker |
| `NEXUS_FIRMWARE`, `NEXUS_VARS` | Matching pflash code and variables files |

`doctor`, `smoke` and `run` also accept `--firmware FILE --vars FILE`. Firmware
discovery covers AAVMF, Arch EDK2 and QEMU/Homebrew's EDK2 files. An executable's
presence is not a supported-backend guarantee: build errors retain the exact
compiler command and stderr.

## Commands and state

```sh
./nexus list
./nexus doctor --json
./nexus fetch
./nexus build
./nexus run --timeout 90
./nexus smoke --timeout 120
./nexus status
```

Global options come **before** the command:

```sh
./nexus --work /path/to/local-work --target /path/to/target.toml smoke
```

An external target file must use an implemented recipe; Nexus never runs
executable hooks from TOML. The HakiOS recipe rejects unknown fields, CPUs and
accelerators instead of quietly applying untested defaults. A changed target
requires a new build. An existing build can run without compiler/Git tools.

The default target uses single-thread TCG and the ordinary host clock, validated
on QEMU 8.2, 10 and 11. In an external target copy, `qemu.clock = "instruction"`
enables faster instruction-count time (`-icount shift=3,align=off,sleep=off`).
Doctor refuses that mode on QEMU below 10 or an unknown version: QEMU 8.2 was
reproduced hanging before loader entry with both firmware versions. With that
optional mode, sleeping advances to the next guest timer and the probe checks
**guest** time, not host performance. One separate host-clock stall remains
unexplained; see the retained evidence. No automatic retry hides a failed boot.

Every attempt lives in a new `.nexus/experiments/<timestamp>-<target>-<operation>-<random>`
directory. Source caches are pristine exact-commit checkouts under `.nexus/sources`.
A failed fetch remains in its experiment and is never published as a valid cache.
Dirty/wrong cached sources are refused, not reset. Preserve edits and choose a
fresh `--work` directory if necessary. No cleanup command removes your work.

### Source mirrors

`upstreams.lock.toml` names each upstream's canonical public HTTPS URL. If that
repository is offline, moved or removed, point Nexus at any copy that still
contains the locked commit:

```sh
NEXUS_MIRROR_HAKIOS=/absolute/path/to/hakios-mirror.git ./nexus smoke
NEXUS_MIRROR_APPLE_XNU=https://example.org/mirrors/xnu.git ./nexus prepare-kernel
```

The variable is `NEXUS_MIRROR_` plus the upstream ID in capitals, with `-` as
`_`. It accepts an HTTPS URL or an existing absolute local repository path.
A mirror cannot change the experiment: the fetched checkout must still be the
locked commit, and kernel/loader artifacts keep their SHA-256 pins. Active
mirrors are recorded in each experiment's `operation.json`. Keep a mirror
(`git clone --mirror URL`) of any upstream you depend on for long-term work.

### What Nexus executes from upstream

Nexus never runs upstream setup, download or build scripts. It does run two
small Python helpers from the **pinned** HakiOS commit: `xnuloader/mkidentity.py
--placeholder` (writes the loader's placeholder identity header during `build`)
and `tools/hakios-config.py` (generates the QEMU configuration during
`prepare-kernel`). Both are recorded in `commands.json`. Review them again when
changing the HakiOS pin.

| Evidence file | Contents |
| --- | --- |
| `operation.json`, `failure.json` | Operation inputs/status; actionable setup/build failure |
| `commands.json`, `step-*.log` | Build/fetch argv, cwd, timing, exit status, stdout/stderr |
| `build.json` | Source pin, kernel origin, tool versions and artifact hashes |
| `inputs.json`, `command.json` | Run configuration, firmware hashes, token, exact QEMU invocation |
| `serial.log`, `qemu.log` | Guest console and emulator errors, kept separately |
| `diagnostics.json` | QMP status, vCPU metadata and register dump |
| `result.json` | Observed stages/checks, liveness, duration, scope and final outcome |
| `prepared.json`, `tree-manifest.json` | Applied source inputs and hashes of the prepared source files |

Build success is `built-not-boot-tested`; source assembly is
`prepared-not-compiled`. Only the live run can report `passed`. Re-running a
build makes new outputs; no old guest state or variable storage is reused.

## Debugging

1. Read `failure.json` for a host/build failure; read `qemu.log` for an emulator
   startup failure. These are different from a guest panic.
2. Read `result.json`: the last reached stage and first incomplete check narrow
   the failure. Read `serial.log` around that transition.
3. Inspect `diagnostics.json` for QEMU status and PC/registers. Keep the failed
   experiment when testing a correction.

```sh
./nexus run --timeout 300 --gdb-port 1234
# In another terminal, with an AArch64-capable GDB:
# target remote 127.0.0.1:1234
```

The guest runs immediately; GDB can interrupt it. The stub binds to loopback
only and is absent by default. It is a debugging channel, not an authenticated
service. QMP itself uses inherited pipes and exposes no port/socket.

Re-analyse a saved log using the expected token from that run's `inputs.json`
or `result.json`:

```sh
./nexus analyze /path/to/serial.log --token 0123456789abcdef0123456789abcdef --json
```

The example token is illustrative. A missing/wrong token, incomplete boot,
missing check, insufficient heartbeats or panic yields exit status 1. The CLI
returns 130 for interruption. A timeout is not an expected successful boot.

## Kernel source

```sh
./nexus prepare-kernel
```

This fetches pinned Apple XNU `xnu-8796.121.2` and HFS `hfs-627.100.6`, checks
both upstream patch series before applying them, overlays the driver sources,
generates HakiOS's QEMU defconfig/driver selection, checks the resulting diff,
and hashes the materialised source tree. Source checkouts remain pristine;
the separate `kernel-source` directory is yours to edit.

**This does not compile XNU.** The pinned HakiOS build expects cctools, MIG,
libpthread/libdispatch support and authorised SDK headers including the private
DriverKit interfaces it describes in `xnu-deps/setup.sh`. No such SDK was supplied
in the reference environment. Its setup script also fetches SDK archives from
third parties, so Nexus deliberately does not invoke it automatically.

After arranging an authorised SDK/toolchain, use the pinned HakiOS source's
`docs/getting-started/building.md`, `xnu-env.sh` and `xnu-build.sh`. Set `XNU_SRC`
to the prepared tree and `THEOS` to your local toolchain layout. Those upstream
steps are **not verified here**. Record their versions and diagnostics; do not
accept a stale kernel just because a build command returned success.

A newly built compatible kernel can use the verified boot/test path:

```sh
./nexus build --kernel /absolute/path/to/mach.development.bcm2837
./nexus run
```

Nexus validates its ARM64 Mach-O layout and records its hash as `user-supplied`.
This makes no automatic source-correspondence or iOS-compatibility claim.

## Tests and contribution checks

```sh
python3 -m unittest discover -s tests -v
git diff --check
```

Unit tests cover evidence false positives, nonce/order/liveness rules, binary
format bounds and static entry conversion, immutable sources and QMP protocol
failures. Protocol fixtures are not guest boot evidence. Public CI separately
boots the real open-source kernel with the source-built loader and probe, and
prepares the real patched source tree; it needs no Apple proprietary assets.

When changing guest/loader/runner behaviour, run a real `smoke`, plus the
relevant failure case. When changing source pins/preparation, run
`prepare-kernel`. Keep small logs/JSON under `docs/evidence/`, never the payload,
firmware, kernel, source archive or user-supplied OS material. Review logs for
secrets before committing them. Update `docs/status.md` with the actual result.

Commit evidence for **milestones and notable failures**, not for every routine
run: usually `result.json`, `serial.log` and the exact command line are enough.
CI already uploads complete records as workflow artifacts. A new dated evidence
directory should explain in its README what it proves and what it does not.
