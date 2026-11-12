# Initial implementation evidence

Reference logs were produced by real QEMU guests on Debian 13 x86_64 with
LLVM 19.1.7, QEMU 10.0.13 and AAVMF 2025.02. Portable comparisons also run the
Ubuntu QEMU 8.2.2/AAVMF 2024.02 binaries on that host; the CI failure logs come
from the actual Ubuntu 24.04 runner. No proprietary Apple assets were
used. Absolute paths in the records identify the original local environment;
follow `docs/development.md` to reproduce in a new checkout.

| Files | Meaning |
| --- | --- |
| [portable-validation.json](portable-validation.json), `qemu8-host-*`, `qemu10-host-*`, `qemu10-instruction-*` | Current fresh-token acceptance boots across QEMU versions/clocks/loaders; 42 unit tests |
| [validation.json](validation.json) | Four earlier fresh-token instruction-clock boots, both loaders; repeated-build hashes; timeout and interrupt attempts |
| [source-result.json](source-result.json), [source-serial.log](source-serial.log) | Source-built placeholder UEFI loader + original probe; ten checks and heartbeats |
| [prebuilt-result.json](prebuilt-result.json), [prebuilt-serial.log](prebuilt-serial.log) | Separately pinned upstream loader through the same live checks |
| `source-` / `prebuilt-inputs.json`, `*-command.json`, `*-build-commands.json`, `*-diagnostics.json` | Exact inputs, compiler/QEMU invocations, return codes and CPU/QMP state |
| [timeout-result.json](timeout-result.json) | Intentional 0.1-second deadline, correctly failed; QEMU stopped cleanly |
| [interrupted-result.json](interrupted-result.json) | Real SIGINT, CLI 130, diagnostics and clean child shutdown |
| [source-preparation.json](source-preparation.json), [source-preparation-commands.json](source-preparation-commands.json), [source-preparation.log](source-preparation.log) | Exact XNU/HFS source assembly, patch checks, QEMU driver generation and prepared-tree manifest hash; not a kernel compilation |
| [unit-tests.log](unit-tests.log) | 42 standard-library tests passing; these are not guest boot evidence |
| [host-clock-stall-result.json](host-clock-stall-result.json), `host-clock-stall-serial.log`, `host-clock-stall-diagnostics.json`, `host-clock-stall-command.json` | A real unexplained UEFI stall with the earlier ordinary host-clock configuration; preserved failure |
| [firmware-followups.json](firmware-followups.json) | Six diagnostic cold replays reached the probe; three with explicit boot order. These reuse a debug payload and are not fresh-token acceptance records. |
| `ci-qemu8-instruction-*`, [boot-media-comparison.json](boot-media-comparison.json), [clock-comparison-host.json](clock-comparison-host.json) | Initial CI freeze and controlled QEMU/firmware/media/clock comparisons. Diagnostic replays reuse a debug payload; the portable acceptance runs above use fresh tokens. |

`source-serial.log` and `prebuilt-serial.log` are unmodified copies. Their SHA-256
values match the corresponding `result.json` records. The recorded build says
`kernel_origin: upstream-prebuilt` and explicitly does not verify its source
correspondence. No kernel, probe binary, firmware, payload, source archive, SDK
or OS image is committed with these logs.

Acceptance is ordered loader → kernel → root → userspace, all ten checks, this
run's expected token, two subsequent heartbeats, no panic and a clean QMP quit.
The default now uses the ordinary clock for compatibility. Optional instruction
time requires QEMU 10+ and measures guest time, not host performance.
The earlier firmware stall remains open; successful replays do not erase it.
