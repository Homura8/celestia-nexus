# Celestia Nexus

A small, agent-independent framework for reproducible Apple OS porting experiments.

**Working today**, as two independent recipes:

- `qemu-virt-xnu` (any Linux/macOS host, no Apple material): boot an open-source
  XNU kernel under QEMU/AArch64, build its UEFI loader and a freestanding Darwin
  test program from source, and verify ten syscall checks plus continued
  userspace execution.
- `ios-qemu-iphonex` (Apple Silicon Mac + **your own** iPhone X iOS 16.7.16
  IPSW): reproduce [ios-qemu](https://github.com/lgrachov/ios-qemu): the stock
  iOS userland boots on patched open-source XNU under HVF to SpringBoard, the
  lock and home screens, and Safari started by injected touch input.
  [Guide](docs/ios-qemu.md).

Both kernels are **hash-pinned upstream builds**, not kernels rebuilt by Nexus.
Nexus also prepares and validates a real patched XNU/HFS source tree. iOS here
is a research environment (no GPU, Secure Enclave or code-signing security), not
a usable device. A separate real-device port now reports iOS with physical touch on the Moto G54; Nexus records its transferable lessons but has no phone execution or flashing recipe.
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

On an Apple Silicon Mac, install Python 3.11+, `qemu`, `llvm` and `lld` with
Homebrew (Homebrew's `llvm` no longer includes the LLD linkers), then put Homebrew
LLVM first on `PATH`:

```sh
brew install python qemu llvm lld
export PATH="$(brew --prefix llvm)/bin:$PATH"
./nexus doctor
./nexus smoke
```

Both hosts are boot-tested: Linux x86_64 locally and in CI, and an Apple Silicon
Mac (macOS 26, Homebrew QEMU 11.1.3 and LLVM/LLD 23.1.4) in [CI](https://github.com/Homura8/celestia-nexus/actions/runs/43179600704). The first
target deliberately uses portable TCG emulation on both; native HVF/KVM
acceleration requires a separately validated boot path.
The default ordinary clock is validated on QEMU 8.2, 10 and 11. An optional faster
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

If a run instead reports that the firmware "never reached the loader", you have
probably hit a rare, known UEFI stall ([status](docs/status.md#2-limits-and-unresolved-findings)).
Run `./nexus run` to boot the same build again; the failed attempt's logs stay
in `.nexus/experiments/` for investigation.

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

[Physical-device bring-up](docs/physical-bringup.md), [G54 engineering lessons](docs/g54-lessons.md) and the [source-pinned port-case index](docs/port-cases/README.md) guide new hardware ports without importing device-specific code.

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
| `nexus`, `nexuslib/core.py`, `nexuslib/cli.py` | Commands (declared per recipe), pinned sources, experiment records |
| `targets/` | Declarative, versioned target inputs; external target files also supported |
| `nexuslib/hakios.py` | Recipe `hakios-open`: build, source preparation, XNUP boot contract and probe checks |
| `nexuslib/iosqemu.py`, `nexuslib/ipsw.py` | Recipe `ios-qemu`: CI kernel, IPSW → disk, live log, screen/touch milestones |
| `nexuslib/qemu.py`, `nexuslib/formats.py` | Shared QMP and process lifecycle; binary formats |
| `guest/probe.c` | Original, SDK-free Darwin syscall regression program |
| `upstreams.lock.toml` | Exact upstream revisions and provenance |
| `docs/status.md` | Verified capabilities, blockers and prioritised next work |
| `docs/port-cases/`, `nexuslib/portcases.py` | Pinned, evidence-labelled reports from external device ports; offline validator, not a phone runner |

There is no agent-provider dependency, package installer, plugin system, or
vendored operating-system tree. [Architecture decisions](docs/architecture.md)
explain why these boundaries are intentionally small.

## 5. Licences and materials

Nexus's original code is MIT licensed. External components retain their own
licences; see [NOTICE](NOTICE) and the upstream lock. No proprietary Apple images,
firmware, keys or credentials are distributed here; the ios-qemu recipe uses
an IPSW you supply, only inside your local `.nexus/` directory. An upstream's inclusion of
a file is not a redistribution clearance; HakiOS itself identifies unresolved
third-party provenance. Source preparation remains local and does not clear
that tree or its outputs for redistribution.

Nexus has no flashing or physical-partition command. Device work needs explicit
authorisation before any destructive operation. Contributions go through pull
requests; see [CONTRIBUTING.md](CONTRIBUTING.md).
