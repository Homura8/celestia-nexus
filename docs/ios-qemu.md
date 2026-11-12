# ios-qemu recipe: stock iOS 16.7.16 userland

Target `ios-qemu-iphonex`, recipe `ios-qemu` (`nexuslib/iosqemu.py`). It
reproduces [lgrachov/ios-qemu](https://github.com/lgrachov/ios-qemu/tree/8d23f48c683250c728a5c820482b450646453c02):
Apple's open-source XNU 8796 plus a 108-patch series, booted directly (no UEFI)
on QEMU's `virt` board with HVF, running the **unmodified iPhone X iOS 16.7.16
(20H392) root filesystem** from your own IPSW. Results: [status](status.md).

This is the second, genuinely different boot path in Nexus: a different kernel
lineage and loader (a 6-instruction stub instead of UEFI), real Apple userland
instead of an original probe, a writable disk instead of a ramdisk, hardware
virtualization instead of TCG, and GUI/input evidence instead of serial checks.

## Host setup

Needs macOS on Apple Silicon (HVF), 16 GiB RAM (the guest gets 7 GiB of
QEMU RAM), about 40 GiB free disk for disk preparation, and:

```sh
brew install qemu rsync gh     # GNU rsync: upstream's disk builder needs it
xcode-select --install         # clang assembles upstream's boot stub
gh auth login                  # only to download the pinned CI kernel once
./nexus --target ios-qemu-iphonex doctor
```

Checked on macOS 27.2.1 / M1 Pro 16 GiB with QEMU 11.1.3 (upstream used macOS
26, an M5 and QEMU 11.0.2). Linux, TCG and Intel Macs are **not** validated.

## IPSW

Download `iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw` from Apple yourself
(Apple's IPSW links are public; Nexus never downloads Apple software). Nexus
checks the BuildManifest (16.7.16, 20H392, iPhone10,3) and the SHA-256 pinned in
[`target.toml`](../targets/ios-qemu-iphonex/target.toml), then extracts only the
OS, SystemOS and AppOS images and the D22AP device tree. The device tree's
LZFSE payload is decoded with macOS's libcompression (no `ipsw` tool needed).
Everything derived from the IPSW stays under `.nexus/` (ignored by Git).
Never commit, upload or attach it to an issue or PR.

## Commands

```sh
T="--target ios-qemu-iphonex"
./nexus $T fetch                      # pinned ios-qemu source; checks patch-tree IDs
./nexus $T build                      # pinned CI kernel (gh, once; cached) + upstream boot tools
./nexus $T prepare-disk --ipsw ~/Downloads/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw
./nexus $T run                        # fresh disk clone, boot, screen + touch checks
./nexus $T run --display --hold 600   # same, with a QEMU window, kept alive 10 min
./nexus $T run --disk .nexus/experiments/<run>/result.json   # continue from a run's disk
./nexus $T analyze .nexus/experiments/<run>/kernel.log
```

`prepare-disk` runs upstream's reviewed `tools/mkiosroot-mac.sh` (copied from
the pinned checkout) under `sudo` **once**: it mounts the images read-only,
creates a case-sensitive journaled HFS+ volume, copies the OS and both
cryptexes keeping root/mobile/_logd ownership, applies `sweet-root-tweaks.py`
(skip Setup, drop CommCenter/locationd, disable crash-looping audio, …) and
wraps the volume as a 4 KiB-sector UFS disk. sudo reads your password from the
terminal; Nexus never sees it. About 5 minutes on an M1 Pro. Extracted images
and the intermediate `root.hfs` are removed afterwards (`--keep-inputs` keeps them).

`run` never writes the prepared disk: it verifies its SHA-256 and boots an APFS
clone (`cp -c`) in the run's directory. Each run is therefore a first boot
(data migration included). `--disk <run>/result.json` boots a clone of that
run's disk instead, for faster later boots and persistent guest state.

## Milestones

Never promoted into each other (`result.json` → `milestones`):

| Milestone | Evidence |
| --- | --- |
| `kernel` | `Darwin Kernel Version` in the kernel message buffer (`kernel.log`) |
| `root` | `BSD root: ufsroot0` (the HFS+ root on emulated UFS), after `kernel` |
| `launchd` | the kernel's one-line exec log `exec launchd`, after `root` |
| `backboardd`, `springboard` | `exec backboardd` / `exec SpringBoard` after launchd, in either order (launchd starts SpringBoard first) |
| `display` | `--settle` seconds later, polled every 10 s: the framebuffer has ≥ 64 colours, no dominant colour, is not blank. The first boot's migration progress bar does not count |
| `interaction` | after an injected unlock swipe and a tap on Safari's dock icon, `exec MobileSafari` appears **after** the tap and the screen differs from the lock screen |

A kernel panic, a `CRASH SpringBoard[…]`/`backboardd` line or a second exec of
either fails the run. `passed` means all seven. `--no-interact` stops at
`display` (`passed-display`). Screens are saved as `springboard.png`,
`unlocked.png`, `app.png` and `final.png`.

The kernel prints no boot-args, so unlike the HakiOS probe there is no boot
token: freshness comes from Nexus reading the log live from this run's guest
RAM (`log_source` in `result.json`). `analyze` on a saved `kernel.log` is
classification only, not proof of a run.

These checks prove a cooperative research guest reached that state in this run.
They are not attestation against a hostile guest, and they are not a usable or
secure iOS device: there is no GPU, Secure Enclave, baseband or code-signing
security, and Apple's security model is mostly switched off by the patches.

## Reading the guest without stopping it

Upstream's launcher follows the kernel log with QMP `x`/`memsave` of kernel
*virtual* addresses (`--live-log`). Those make QEMU wait until a vCPU leaves
the guest. On an M1 Pro with macOS 27.2.1 and QEMU 11.1.3 that wait never
ended: QEMU's main loop froze (UFS, network, QMP all stopped) while four vCPUs
kept running. This reproduces on demand with 0.2 s polling from early boot
([evidence](evidence/2026-11-12-ios-qemu/README.md)). It was not reported upstream
(M5, macOS 26, QEMU 11.0.2); the root cause in QEMU/HVF is not established.

Nexus therefore never asks QEMU for virtual memory or registers. It reads
`_msgbufp` from the kernel's own symbol table, translates kernel-image
addresses linearly (payload `virt_base` → `phys_base`) and heap addresses by
walking the kernel page tables from `kernel_pmap_store`, and fetches only
physical memory with QMP `pmemsave`. Ring snapshots are merged by overlap, so
wrap-around and resizes neither duplicate nor silently drop lines (a real gap
is marked in the log and counted in `log_gaps`). If QMP still stops answering
for 30 s, the run fails fast with that diagnosis.

## Stopping

Ctrl-C, SIGTERM or SIGHUP, a timeout, or a finished check all lead to the same
bounded stop (each step is timed in `result.json` → `shutdown_steps`):

1. QMP `quit` (normally 0.1–0.2 s);
2. if QEMU survives, SIGTERM then SIGKILL its exact pid (`qemu.pid`);
3. the launcher then exits; otherwise SIGTERM/SIGKILL its process group.

A second Ctrl-C during these ~25 s cannot abort them. The 10 s hash of the disk
clone (for `--disk` reuse) runs afterwards, is skipped after an interruption,
and a Ctrl-C skips it. `run` refuses to start while another ios-qemu guest is
still running and names its pid.

## Network

Like upstream, the guest has QEMU user-mode networking (NAT, DHCP 10.0.2.15),
so iOS daemons contact Apple and other servers from your Mac as soon as they
start. The device identity is synthetic (`QEMU00000001`). The upstream
launcher has no switch to disable this; `--mux-port 0` is passed so no host
port is opened.

## Files of a run

| File | Contents |
| --- | --- |
| `inputs.json`, `command.json` | build/disk records, boot-args, exact launcher argv |
| `kernel.log` | kernel message buffer, read from guest physical memory every 2 s |
| `launcher.log`, `qemu/qemu.log` | upstream launcher output; QEMU `-d int,guest_errors,unimp` |
| `qemu.pid` | the exact QEMU process, for bounded shutdown |
| `*.png`, `result.json` | screens, milestones with times, interaction, shutdown steps, disk hashes |

`kernel.log` and screenshots can contain Apple-generated text and images:
commit only short excerpts as evidence (see `docs/evidence/`).

## Kernel

`build` downloads the `xnu-kernel` artifact of upstream CI run
[40196425620](https://github.com/lgrachov/ios-qemu/actions/runs/40196425620)
(the run upstream's NOTES name as their working kernel) with `gh`, verifies the
kernel's SHA-256 and caches it under `.nexus/downloads/`. `fetch`/`build` verify
that the pinned checkout's `xnu/patches` tree and workflow are byte-identical to
that run's commit, so source and binary describe the same patch series. Nexus
did **not** rebuild it; correspondence rests on GitHub's run record.

GitHub deletes the artifact on **2027-01-23**. Keep `.nexus/downloads/`, or
rebuild and pass `--kernel`:

```sh
./nexus $T build --kernel /path/to/kernel.development.sweet
```

Upstream builds with `.github/workflows/xnu.yml` on a fork. That workflow pins
`macos-14` (Xcode 15's `iig` matches XNU 8796's IORPC ABI), and GitHub retired
macOS 14 runners on 2 November 2026; a rebuild needs an Xcode 15 toolchain on
your own Mac or an adapted workflow. Not attempted here.
