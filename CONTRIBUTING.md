# Contributing

Read [AGENTS.md](AGENTS.md) for the small task map and
[docs/development.md](docs/development.md) for executable workflows. Human and
agent contributions use the same interfaces and evidence requirements.

1. Start from `docs/status.md` and preserve unrelated work on your branch.
2. Implement a coherent improvement with the smallest useful dependency set.
3. Run the relevant unit checks and real experiment. Keep failure diagnostics.
4. Update status/research when a finding would otherwise need rediscovery.
5. Open a PR describing behaviour, evidence, limits and the next useful step.

Public tests must work without proprietary Apple assets. Use synthetic format
and protocol fixtures for negative cases, and real QEMU boots for boot claims.
Never treat an earlier boot stage or a successful compile as a complete boot.

Retain upstream notices and provenance. Original Nexus contributions use the
MIT licence in LICENSE; upstream derivatives keep their original terms. A source
pin does not settle redistribution rights. Do not publish generated source
trees/binaries until their component licences and provenance have been reviewed.

CI has read-only repository permissions, uses pinned actions and has no need
for secrets. Do not add `pull_request_target` execution of contribution code,
privileged containers, unreviewed setup scripts or automatic merges.
