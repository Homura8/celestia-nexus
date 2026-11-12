# ios-qemu recipe evidence — 12 November 2026

Host: Apple M1 Pro, 16 GiB, macOS 27.2.1, Homebrew QEMU 11.1.3 (HVF),
Python 3.15.2, GNU rsync 3.5.2. Recipe `ios-qemu`, target `ios-qemu-iphonex`.
Inputs: ios-qemu `8d23f48`, CI kernel `70d1ed6a…` (run 40196425620), the user's
own iPhone X 16.7.16 (20H392) IPSW `ece1194f…`, prepared disk `f40b8061…`.

Home and temporary directories are redacted (`~`, `$TMPDIR`). Screenshots and
full kernel logs stay local: they show Apple software and are not committed.
Their SHA-256 and colour statistics are in each `result.json` → `screens`.

## What passed

| File | Shows |
| --- | --- |
| `fresh-pass-result.json`, `-command.json`, `-commands.json`, `-kernel-excerpt.log` | **Default path, fresh disk clone:** all seven milestones. Kernel, root, launchd, SpringBoard and backboardd within the first 2 s poll; first-boot migration; lock screen accepted at 105 s; injected unlock reaches the home screen; injected tap at (433, 2267) logs `SWEET HID: touch 0 down/up` and `exec MobileSafari` 10 ms later; screen 99.9 % changed. QMP `quit` in 0.11 s. 128 s total, 0 read errors, 0 log gaps |
| `continue-pass-result.json`, `-kernel-excerpt.log` | Same seven milestones booting `--disk` from a previous run's disk (migration already done): lock screen at 64 s, Safari at 84 s |
| `prepare-disk.json`, `prepare-disk-commands.json` | IPSW manifest/SHA-256 check, extracted members with hashes, decoded D22AP device tree, upstream disk tools copied and hashed, the single `sudo` builder invocation (about 5 min), resulting disk hash |
| `build.json` | Pinned CI kernel downloaded with `gh`, SHA match, patch-tree check, upstream boot tools hashed |
| `lifecycle-checks.json` | Bounded shutdown against real QEMU: timeout, SIGINT, SIGTERM (exit 130 within 0.2 s, QMP `quit`), and a deliberately wedged QEMU (see below) stopped by killing the exact pid in 3.1 s; no QEMU left in any case |
| `unit-tests.log` | 75 unit tests, including the IM4P/IPSW readers, milestone analyzer, physical log reader (page walk, wrap, resize, gap) and fake launcher/QEMU lifecycle cases |

`implementation.sha256` in the passing results is `8a70de1b…`. The committed
tree differs only in the `role` text of `upstreams.lock.toml` (no code change).

## Notable failures kept on purpose

| File | What happened |
| --- | --- |
| `run1-stall-result.json`, `run1-hvf-stall-msgbuf.txt` | First boot with upstream's `--live-log`: the kernel reached launchd, then QEMU's main loop froze inside a QMP `memsave` of a kernel virtual address (`qmp_memsave → cpu_memory_rw_debug → do_run_on_cpu`, `sample` of QEMU) while all four vCPUs stayed in `hv_vcpu_run`. The 52 KiB of message buffer saved before the freeze is the `.txt`. Timed out after 900 s; cleanup then took about a minute (launcher SIGKILL after 60 s, then a `ps` scan) — the trigger for the lifecycle rework |
| `lifecycle-checks.json` → `wedged-timeout` | The same freeze reproduced on demand by issuing upstream-style `memsave` reads every 0.2 s from early boot; the second entry shows the fail-fast diagnosis after 30 s of unanswered QMP |
| `tap-miss-result.json`, `-kernel-excerpt.log` | Everything up to the home screen passed; the tap at upstream README's (561, 2259) reached the guest but hit the gap between the Safari and Messages dock icons, so no app started and the run failed honestly |
| `prepare-disk-permission-failure.json` | First disk build: upstream's script created the output directory as root, so Nexus could not delete the 11 GB intermediate `root.hfs`. Fixed by creating the directory first; the disk was rebuilt from scratch |

## What this does not show

- A rebuilt or source-identical kernel: the binary is upstream's CI artifact,
  matched to the pinned patch series by Git object IDs only.
- Web browsing, sound, App Store, Metal remoting or multi-hour stability.
- Any host other than this M1 Pro; Linux/TCG is not attempted.
- Attestation against a hostile guest, or a usable/secure iOS device.
- The root cause of the QMP/HVF freeze in QEMU or Hypervisor.framework.
