# Celestia Nexus

A small, agent-independent framework for reproducible Apple OS porting experiments.

**Working today:** boot an open-source XNU kernel under QEMU/AArch64, build its UEFI
loader and a freestanding Darwin test program from source, and verify ten syscall
checks plus continued userspace execution. No IPSW, Apple SDK, Apple firmware or
physical device is needed for this path.

The kernel itself is a **hash-pinned HakiOS prebuilt**, not a kernel rebuilt by
Nexus. Nexus also prepares and validates a real patched XNU/HFS source tree.
Stock iOS/iPadOS/macOS userland, a GUI, and physical-device ports are future work.
[Measured results and limitations](docs/status.md) · [Research](docs/research.md)

## 1. First run

You need Python 3.11+, Git, QEMU's AArch64 emulator, matching non-Secure-Boot
AArch64 UEFI firmware, and LLVM's Clang/LLD. The example guest uses about 6 GiB
of virtual RAM; allow at least 8 GiB of host RAM and 1 GiB of free disk space.

On Debian 13:

```sh
sudo apt-get install python3 git qemu-system-arm qemu-efi-aarch64 clang-19 lld-19
git clone https://github.com/Homura8/celestia-nexus.git
cd celestia-nexus
./nexus doctor
./nexus smoke
```

On an Apple Silicon Mac, install Python 3.11+ plus `qemu` and `llvm` with
Homebrew, then put Homebrew LLVM first on `PATH`:

```sh
brew install python qemu llvm
export PATH="$(brew --prefix llvm)/bin:$PATH"
./nexus doctor
./nexus smoke
```

The Linux reference environment has been tested. macOS execution is **implemented
but not locally boot-tested**; the first target deliberately uses portable TCG
emulation. Native HVF/KVM acceleration requires a separately validated boot path.
The default ordinary clock supports QEMU 8.2 and 10. An optional faster
instruction-count clock is gated to QEMU 10+; it measures guest time, not hardware
performance. QEMU 8.2 hangs with that optional mode, so Nexus refuses it early.
See [host setup](docs/development.md#host-setup) if doctor reports missing tools.

`smoke` checks the host, fetches one exact upstream revision, verifies the kernel,
builds the loader/probe, boots QEMU, and stops it after a validated result. It
downloads open-source upstream material, never operating-system images.

Expected output:

```text
passed: .../.nexus/experiments/<unique-run>
Open XNU userspace probe passed; this does not establish an iOS/userland/GUI boot.
```

## 2. Iterate

```sh
./nexus list                  # implemented targets
./nexus fetch                 # exact source, no upstream setup scripts
./nexus build                 # source loader + no-SDK test program
./nexus run                   # rerun the latest build, fresh guest state
./nexus prepare-kernel        # pinned XNU + HFS + real patches + QEMU configuration
./nexus status                # latest experiment paths
python3 -m unittest discover -s tests -v
```

Each experiment keeps its commands, return codes, tool versions, input/output
hashes and diagnostic logs in `.nexus/experiments/`. `result.json` explains which
boot stages and checks were observed. The serial log, not a screenshot or an
early kernel banner, determines the result. A timeout or panic is a failure.

[Development and debugging](docs/development.md) explains custom kernels,
firmware overrides, saved-log analysis and the GDB stub.

## 3. Work with an agent

Start with [AGENTS.md](AGENTS.md). You can ask:

> Reproduce the QEMU baseline, then investigate the highest-priority unfinished
> item in docs/status.md. Keep evidence and open a pull request.

The eventual goal is “Port iOS [version] to [device] using Celestia Nexus.” Today
an unknown device starts a research/bring-up task; that sentence cannot make
unsupported hardware work automatically. [Porting guidance](docs/porting.md)
identifies what to establish before implementation.

## 4. Structure

| Path | Responsibility |
| --- | --- |
| `nexus`, `nexuslib/core.py`, `nexuslib/cli.py` | Commands, pinned sources, experiment records |
| `targets/` | Declarative, versioned target inputs; external target files also supported |
| `nexuslib/hakios.py` | First concrete build/source-preparation recipe |
| `nexuslib/qemu.py`, `nexuslib/formats.py` | First boot contract, QMP, binary formats and evidence checks |
| `guest/probe.c` | Original, SDK-free Darwin syscall regression program |
| `upstreams.lock.toml` | Exact upstream revisions and provenance |
| `docs/status.md` | Verified capabilities, blockers and prioritised next work |

There is no agent-provider dependency, package installer, plugin system, or
vendored operating-system tree. [Architecture decisions](docs/architecture.md)
explain why these boundaries are intentionally small.

## 5. Licences and materials

Nexus's original code is MIT licensed. External components retain their own
licences; see [NOTICE](NOTICE) and the upstream lock. No proprietary Apple images,
firmware, keys or credentials are distributed here. An upstream's inclusion of
a file is not a redistribution clearance; HakiOS itself identifies unresolved
third-party provenance. Source preparation remains local and does not clear
that tree or its outputs for redistribution.

Nexus has no flashing or physical-partition command. Device work needs explicit
authorisation before any destructive operation. Contributions go through pull
requests; see [CONTRIBUTING.md](CONTRIBUTING.md).
