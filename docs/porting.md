# Continuing a port or adding a target

## Start from a specific request

For “Port iOS 16.7.16 to my [device]”, establish the exact device variant, SoC,
OS build/product identity, host, available assets and bootloader state. Search
the existing target list and research record before asking the owner for facts
the repository or read-only tooling can already provide. A marketing name alone
does not establish CPU features, page-size compatibility or a usable boot path.

For an unknown device, first create a concise research/status record with source
links and next experiment. This is progress, not a supported-target claim.
Do not fabricate addresses, firmware requirements, an unlock procedure or drivers.

## Establish a practical path

Compare the strongest available approaches:

- An existing source-XNU port on generic hardware (HakiOS, ios-qemu).
- UniXNU's UEFI/platform/OS build and driver components.
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

## Extend the implementation only where needed

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

## Preserve the handoff

In the same PR, record:

- What was actually reached, on which host/target, with commands and hashes.
- Which claims are upstream reports, locally reproduced, partial, untested or blocked.
- Failed experiments and their concrete reason; do not repeat them without new evidence.
- The next smallest useful experiment and any exact human/asset requirement.

Never commit an IPSW, SDK, device firmware, encryption key or account material.
Do not issue device boot/flash/partition commands without the required explicit
authorisation. Nexus currently has no physical-device execution interface.
