# Port cases: source-backed lessons, not cloned device ports

Each JSON file is one **sanitised snapshot** of a real port. Its `source.commit`
pins a Git tree; `source.review` is a convenient but mutable discussion link.
An agent can get a small, evidence-linked overview without reading the complete
device repository:

```sh
python3 -m nexuslib.portcases check
python3 -m nexuslib.portcases show --id moto-g54-ios16-20261113
```

This command only reads local JSON. It does **not** fetch upstream sources,
execute arbitrary code, connect to devices or update any files. The checker
enforces a full Git SHA, source-shaped evidence paths, unique claim IDs,
milestone provenance and allowed confidence/scope labels. It cannot independently
authenticate claims in another repository: inspect the linked experiment and
check its source revision when it matters.

## Reading the labels

- **owner-observed**: original port author/owner reported the hardware outcome,
  backed by a public run card. It was *not* reproduced by Nexus.
- **host-verified**: host-side command/build/image verification in the source
  project; does not prove device execution.
- **upstream-reported**: third-party report without Nexus reproduction.
- **hypothesis** / **not-tested**: open work, never a passed milestone.
- **general**: cross-hardware workflow or evidence invariant.
- **conditional**: a method that transfers after verifying its preconditions
  (controller, memory/ABI, firmware protocol, OS version).
- **device-specific**: an observed value or patch that must not be copied as
  a platform-independent default.

In the case file, `milestones` are verified/observed claims; `lessons` have
a finding, a future application and a limitation; `open_questions` name a
bounded next test. Every entry links to documentation inside the pinned tree.

## Bringing in another port

1. Identify the **device variant, SoC, OS build, exact source commit and
   authoritative repository**. Read its active development branch/PRs, not
   just its default branch. Freeze a snapshot once the claims are checked.
2. Build a short sequence of independent milestones: bootloader execution,
   kernel entry, interrupt/VM, storage, mounted root, PID 1, rendered interface,
   *physical* interaction. Skip inapplicable stages but never infer a later
   stage from a prior one.
3. Record failures as well as successes. For each lesson, state what was
   measured, what may transfer and the mechanism/assumptions that may not.
4. Keep all code and live device facts with the originating port; link to its
   experiment paths. Do not commit full logs, screenshots, user paths, serials,
   Apple assets, firmware, proprietary binaries, unlock data or keys.
5. Run the checker and tests; add a short link in
   [the porting guide](../porting.md). A later upstream update creates a
   reviewed snapshot change with a new source SHA and corrected evidence.
   Never quietly move the SHA to follow a branch.

The validator checks **shape and provenance discipline**, not experimental
truth, licences, privacy of free-form prose or capability compatibility. Human
review must check those. Nexus gains shared driver/build code only when a
second implementation justifies it and its licence is compatible.

Current case: [Moto G54 / iOS 16.7.16](g54-2026-11-13.json).
Technical synthesis: [G54 lessons](../g54-lessons.md).
