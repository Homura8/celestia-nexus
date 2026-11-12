# Continuing a port or adding a target

## 1. Look for an existing port

Someone may already have started your device or its SoC. Check, in order:

1. Nexus's own `./nexus list` and [status](status.md).
2. UniXNU's device registry,
   [`devices.toml`](https://github.com/UniXNU/UniXNU/blob/main/devices.toml): search
   for the device's codename, marketing name and SoC (for example `SM8250`,
   `MT6877`). Each record links the port's own repository, its SoC, its OS
   profile and a short status.
3. HakiOS's [`devices/manifest.conf`](https://github.com/oosexgang/hakios-xnu-kernel/blob/main/devices/manifest.conf)
   and its README's repository table.

A port of the **same SoC** is often the most valuable find, even for a different
phone: interrupt controller, timers, clocks, storage and display controllers
are SoC facts. Treat registry summaries as maintainer reports until you
reproduce them, and record what you found (or that nothing exists) in the
status/research record. See [research §7](research.md#7-existing-device-ports-and-phone-workflows)
for what these projects already provide, including physical-phone workflows.

## 2. Pin down the request

For “Port iOS 16.7.16 to my [device]”, establish the exact device variant, SoC,
OS build/product identity, host, available assets and bootloader state. Use the
existing ports found above and the research record before asking the owner for
facts the repository or read-only tooling can already provide. A marketing name alone
does not establish CPU features, page-size compatibility or a usable boot path.

For an unknown device, first create a concise research/status record with source
links and next experiment. This is progress, not a supported-target claim.
Do not fabricate addresses, firmware requirements, an unlock procedure or drivers.

## 3. Establish a practical path

Compare the strongest available approaches:

- An existing source-XNU port on generic hardware (HakiOS, ios-qemu).
- UniXNU's UEFI/platform/OS build and driver components, and its device ports.
- A stock-kernel Apple-device emulator (darwin-vm, Inferno).

Choose based on the requested OS, hardware and reproducible evidence. A device
emulator can validate OS internals without validating native phone drivers.
An existing generic-hardware driver is useful only if its register/interrupt,
DMA/IOMMU, cache, power and firmware assumptions match the new platform.

Record exact CPU architecture/features, exception level, MMU/page granule,
interrupt controller/timer, usable RAM/boot handoff, console, storage and required
proprietary inputs. Bring up the smallest observable end-to-end experiment;
expand only after it passes. Keep native/emulated and reported/reproduced
capabilities separate.

## 4. Extend the implementation only where needed

Existing compatible QEMU experiments can keep their TOML in an independent repo:

```sh
./nexus --target /path/to/my-port/target.toml smoke
```

That file still uses `hakios-open` and its validated constraints. New hardware
or a substantially different boot environment needs a new **concrete recipe**,
registered explicitly in `nexuslib/cli.py`, with its own validation, build inputs
and evidence checks. Do not weaken the working recipe until untested settings
appear to fit. Share source fetching and records; share boot/driver code only
when both implementations exercise it.

Use independently maintained upstream SoC/device repositories when they already
solve the problem. Keep common fixes upstream or as small attributed patches
with their base revision and licence. An external repo does not have to move
its device tree, firmware extractor or entire kernel into Nexus.

## 5. Preserve the handoff

In the same PR, record:

- What was actually reached, on which host/target, with commands and hashes.
- Which claims are upstream reports, locally reproduced, partial, untested or blocked.
- Failed experiments and their concrete reason; do not repeat them without new evidence.
- The next smallest useful experiment and any exact human/asset requirement.

Never commit an IPSW, SDK, device firmware, encryption key or account material.
Do not issue device boot/flash/partition commands without the required explicit
authorisation. Nexus currently has no physical-device execution interface. Until
it does, use the upstream's own RAM-only workflow (HakiOS `xl`, UniXNU's staged
`fastboot boot`), confirm the owner has a way back to stock firmware, and keep
the exact commands, versions and logs as evidence.
