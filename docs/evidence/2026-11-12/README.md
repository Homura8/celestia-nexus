# Initial implementation evidence

All boot logs here were produced by real QEMU guests on Debian 13 x86_64 with
LLVM 19.1.7, QEMU 10.0.13 and AAVMF 2025.02. No proprietary Apple assets were
used. Absolute paths in the records identify the original local environment;
follow `docs/development.md` to reproduce in a new checkout.

| Files | Meaning |
| --- | --- |
| [validation.json](validation.json) | Four final fresh-token instruction-clock boots, both loaders; repeated-build hashes; timeout and interrupt attempts |
| [source-result.json](source-result.json), [source-serial.log](source-serial.log) | Source-built placeholder UEFI loader + original probe; ten checks and heartbeats |
| [prebuilt-result.json](prebuilt-result.json), [prebuilt-serial.log](prebuilt-serial.log) | Separately pinned upstream loader through the same live checks |
| `source-` / `prebuilt-inputs.json`, `*-command.json`, `*-build-commands.json`, `*-diagnostics.json` | Exact inputs, compiler/QEMU invocations, return codes and CPU/QMP state |
| [timeout-result.json](timeout-result.json) | Intentional 0.1-second deadline, correctly failed; QEMU stopped cleanly |
| [interrupted-result.json](interrupted-result.json) | Real SIGINT, CLI 130, diagnostics and clean child shutdown |
| [source-preparation.json](source-preparation.json), [source-preparation-commands.json](source-preparation-commands.json), [source-preparation.log](source-preparation.log) | Exact XNU/HFS source assembly, patch checks, QEMU driver generation and prepared-tree manifest hash; not a kernel compilation |
| [unit-tests.log](unit-tests.log) | 41 standard-library tests passing; these are not guest boot evidence |
| [host-clock-stall-result.json](host-clock-stall-result.json), `host-clock-stall-serial.log`, `host-clock-stall-diagnostics.json`, `host-clock-stall-command.json` | A real unexplained UEFI stall with the earlier ordinary host-clock configuration; preserved failure |
| [firmware-followups.json](firmware-followups.json) | Six diagnostic cold replays reached the probe; three with explicit boot order. These reuse a debug payload and are not fresh-token acceptance records. |

`source-serial.log` and `prebuilt-serial.log` are unmodified copies. Their SHA-256
values match the corresponding `result.json` records. The recorded build says
`kernel_origin: upstream-prebuilt` and explicitly does not verify its source
correspondence. No kernel, probe binary, firmware, payload, source archive, SDK
or OS image is committed with these logs.

Acceptance is ordered loader → kernel → root → userspace, all ten checks, this
run's expected token, two subsequent heartbeats, no panic and a clean QMP quit.
The default instruction-count clock measures guest time, not host performance.
The earlier firmware stall remains open; successful replays do not erase it.
