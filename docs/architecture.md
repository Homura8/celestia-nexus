# Architecture decisions

## 1. Reproduce a complete small environment first

The first milestone is a booted open XNU kernel running an original, freestanding
Darwin PID 1, with ten syscall checks and continuing timer-driven heartbeats.
This is narrower than upstream GUI demonstrations, but unlike those paths it
can run on an x86 Linux host without an Apple SDK or IPSW. It gives contributors
a fast executable regression boundary while userland integration is researched.
It must not become a substitute for reproducing the more advanced paths.

The kernel is an externally fetched, SHA-256-pinned HakiOS prebuilt. Its source
correspondence is not independently established. The source-built loader and
probe are separate outputs. `prepare-kernel` verifies source assembly without
calling it a compiled or boot-tested kernel.

## 2. Common orchestration, concrete recipes

The only common target facts are identity, description, architecture, recipe and
primary source. `core.py` handles lock files, safe paths, source checks and
command/evidence records. It knows no QEMU memory map, phone vendor or OS ABI.

The explicit `hakios-open` recipe validates its own configuration, prepares real
sources and builds real outputs. `qemu.py` implements this first boot contract
and QMP/lifecycle handling; `formats.py` implements the binary interfaces actually
used. These are **not** claims of a universal boot protocol. When a second real
boot path needs the runner, split out the shared process/QMP mechanics then.

Known first-recipe assumptions outside `hakios.py`, to move when the second
recipe arrives (instead of adding `if recipe == ...` branches):

- `cli.py`: the `--loader`, `--kernel`, `--firmware`, `--vars` options and the
  `prepare-kernel` command; `read_build` expects exactly the artifacts `kernel`,
  `probe` and `loader.efi`. Let each recipe declare its options and validate its
  own build record.
- `qemu.py`: `run` hard-codes the XNUP payload at `0xF0000000`, the `cpus=1`
  boot argument, the HakiOS loader banner in `STAGES` and the probe's `CHECKS`.
  Keep QMP, process lifetime and log-size limits shared; pass the payload,
  stages and acceptance checks in from the recipe.
- Upstream pins come only from Nexus's own `upstreams.lock.toml`. An external
  `--target` repository cannot yet pin additional sources of its own.

The CLI registers reviewed modules explicitly. TOML cannot select a Python
import, shell script, executable hook or destructive action. There is no plugin
loader, class hierarchy, dependency resolver or separate agent runtime.

## 3. Reuse upstream implementations without absorbing their assumptions

Nexus is the reproducible experiment and agent-handoff layer **above** porting
projects, not another porting framework. HakiOS and UniXNU already maintain
device/SoC layers, configuration systems, device registries and physical-phone
workflows (see [research](research.md#7-existing-device-ports-and-phone-workflows)).
A device port normally lives in, or next to, one of those upstreams; Nexus
pins it, runs it with recorded inputs and strict acceptance checks, and keeps
the handoff.

Keep upstream trees out of Nexus Git history. Fetch exact commits locally,
verify clean checkouts and artifact hashes, retain licences, and refer fixes
upstream where possible. HakiOS kernel/UEFI conventions remain in its recipe;
they do not become requirements for all future targets.

UniXNU already offers device/SoC repositories, UEFI drivers, OS profiles and
prelink/build machinery. Reimplementing these in Nexus before reproducing them
would add maintenance with no evidence of benefit. A future UniXNU or ios-qemu
recipe should retain its upstream's build boundary and translate inputs/results.
The [research comparison](research.md) explains the alternatives.

Upstreams can disappear: a pin records *what* to fetch, not a guarantee that it
stays available. `NEXUS_MIRROR_<ID>` fetches the same locked commit from a
mirror or local copy, and canonical lock URLs may use any public HTTPS Git host.

Independently maintained ports can keep target TOML, patches and research in
their own repository and use `--target /path/to/target.toml`. The existing recipe
still validates only HakiOS/QEMU; external TOML is not automatic support for new
hardware. SoC/OS/device sharing should follow demonstrated implementations,
not a required directory hierarchy invented in advance.

## 4. Evidence is part of the interface

Every attempt gets a unique directory. No existing edited experiment is reset.
Build records say `built-not-boot-tested`; prepared trees say
`prepared-not-compiled`; run results record exact reached stages and failures.
Each boot uses a fresh token through `boot_args` → `kern.bootargs` → PID 1 and
requires all checks, two subsequent heartbeats and no panic. This prevents
accidental stale-log/early-stage passes, not malicious guest forgery.

QMP uses inherited pipes, avoiding sockets, exposed management ports and path
length limits. ESP access is read-only, pflash variables are copied per run,
networking is absent, and a GDB stub is opt-in and bound to loopback.
Timeouts, interrupts and failed QEMU launches preserve diagnostics.

The default uses the ordinary clock, verified on QEMU 8.2 and 10. Optional
instruction-count time (`shift=3`, `sleep=off`) speeds the regression cycle on
QEMU 10+, but is refused on older/unknown versions. A controlled reproduction
found that QEMU 8.2 hangs before loader entry in that mode with either tested
firmware; changing only the clock lets the same inputs boot. Real FAT versus
vvfat media did not resolve it, so no FAT-image builder/dependency was added.
With instruction time, sleeping advances to the next guest timer; that mode is
not a wall-clock or cycle-accurate performance test. A separate earlier
host-clock stall remains unexplained; no claimed fix or retry hides it.

## 5. An SDK-free test executable

LLD 19's Mach-O `-static` is unimplemented. Nexus links an original program
without libraries, validates that there are no dyld rebases/bindings or dependent
libraries, and replaces `LC_MAIN`/the dyld command with `LC_UNIXTHREAD` in reserved
header space. The ARM64 thread layout comes from Apple's published XNU headers.
Only Nexus's own probe is transformed; no Apple binary is patched by this step.
Malformed, signed, dependent and insufficiently padded inputs are rejected.

The alternative was fetching a proprietary SDK or maintaining another linker.
The small, format-checked conversion has already booted and is regression-tested.
If a supported linker gains native static output, prefer deleting this step.

## 6. Deliberate limits

No automatic OS download/decryption, kernel-security bypass toolkit, firmware
flashing, physical partition writing, driver model, universal hardware discovery
or promise that arbitrary OS/device pairs are compatible. No accelerator switch
that silently changes timer/CPU/boot assumptions. Those require a real target,
explicit inputs and executable evidence before they belong in the framework.
