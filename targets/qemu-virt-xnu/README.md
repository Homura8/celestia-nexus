# QEMU virt / open XNU

Implemented recipe: `hakios-open`. This is the first validation environment,
not a phone hardware abstraction or a complete Darwin distribution.

| Component | Input / result |
| --- | --- |
| Kernel | HakiOS prebuilt, XNU 8796.121.2 / Darwin 22.5.0, SHA pinned in `target.toml` |
| Loader | HakiOS UEFI source, placeholder identity, built with Clang + lld-link |
| Userspace | Original `guest/probe.c`, static ARM64 Mach-O, no SDK/libraries |
| Machine | Stock QEMU `virt`, GICv3, Cortex-A76, 1 CPU, single-thread TCG, 6 GiB RAM |
| Clock | Instruction count, `shift=3,align=off,sleep=off`; guest time, not a performance model |
| Boot | Matching 64 MiB pflash firmware/vars; read-only ESP; XNUP at `0xF0000000` |
| Verified endpoint | PID 1 syscall suite, fresh token, two heartbeats, no panic |

```sh
./nexus doctor
./nexus smoke
./nexus run --timeout 90
```

The ten checks are console I/O, PID 1, UID 0, sysctl, boot-token transport,
ENOENT/carry error reporting, anonymous memory writes/readback, mprotect, munmap,
and a timer/select delay of at least 0.9 guest seconds. PID 1 never intentionally exits.

The pinned upstream's bundled hello prints userspace output then exits/panics;
its prebuilt does not honour the current source's `hello_wait` option. Nexus's
probe fixes the regression-test behaviour without claiming to repair XNU.

`--loader prebuilt` exercises the separately hashed upstream loader instead.
`build --kernel /path/to/kernel` exercises a newly built compatible kernel.
`prepare-kernel` produces the actual patched source tree and QEMU configuration;
it does not compile that tree or establish correspondence to the prebuilt.

See [development](../../docs/development.md) for setup/debugging and
[status](../../docs/status.md) for committed evidence and limits.
