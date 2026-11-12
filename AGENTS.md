# Celestia Nexus: agent entry point

Goal: make progressively more ambitious Apple OS ports reproducible. Ship a
verified experiment, not a new collection of promises. No particular agent,
provider, IDE, or orchestration tool is assumed.

## Start here

1. Read `docs/status.md`: actual capabilities, evidence, blockers, next work.
2. Run `git status --short`, `./nexus list`, and the relevant checks below.
3. Read only the task-specific guide:

| Task | Read |
| --- | --- |
| Reproduce/debug QEMU | `docs/development.md`, `targets/qemu-virt-xnu/README.md` |
| Change boundaries or add a recipe | `docs/architecture.md`, `nexuslib/hakios.py` |
| New upstream/research | `docs/research.md`, `upstreams.lock.toml` |
| New device or OS version | `docs/porting.md` |

## Working rules

- Preserve unrelated work. Use a branch and a reviewable PR; never auto-merge.
- Shared orchestration belongs in `core.py`; HakiOS/QEMU/OS assumptions belong
  in concrete recipes. Add a shared abstraction only after real targets need it.
- Python 3.11+ standard library, original C where necessary. No new dependency
  or provider-specific instruction tree without a demonstrated need.
- Use `./nexus fetch`, not a moving upstream branch. Do not edit cached sources;
  `prepare-kernel` creates a separate editable experiment. Keep patches/provenance
  in Git and generated binaries/OS assets in ignored local work directories.
- Review downloaded scripts before execution. Record exact revisions, licences,
  commands, host/tool versions, hashes, observed milestones and failure reasons.
- Compilation, kernel entry, PID 1, stock launchd and a usable GUI are different
  milestones. Never promote one into another. Do not label fixtures as boots.
- Do not fetch or redistribute proprietary OS assets, firmware, SDKs, keys or
  credentials on the user's behalf without an appropriate user-supplied source
  and authorisation. Do not flash hardware or write physical partitions without
  explicit authorisation. The initial QEMU path needs none of these materials.
- A nonce proves a fresh cooperative test run, not security against a malicious
  guest. QEMU and upstream code remain untrusted; no secrets are needed in CI.

## Verify and hand off

```sh
python3 -m unittest discover -s tests -v
./nexus doctor
./nexus smoke                     # when QEMU or guest behaviour changes
./nexus prepare-kernel            # when source preparation or upstream pins change
git diff --check
```

Use each experiment's `failure.json`, `serial.log`, `qemu.log`, `commands.json`,
`diagnostics.json`, `build.json` and `result.json` to diagnose it. Keep the
smallest useful, asset-free evidence under `docs/evidence/`. Update
`docs/status.md` in the same PR: what changed, what actually passed, what failed,
and the next concrete step. Update `docs/research.md` for expensive findings or
rejected approaches. The repository is the handoff; chat history is optional.
