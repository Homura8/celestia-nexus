"""User commands. The selected target's recipe declares its commands and options.

A recipe module provides: COMMANDS (name -> help), add_arguments(name, parser),
validate_target(target), doctor(target, args), build_command(ctx),
read_build(path), run_command(ctx, build), EXTRA (name -> (latest kind,
function(ctx) -> (result, record file))), analyze_command(args), SETUP_HINT,
READY and SUCCESS. Nothing here knows a payload address, firmware or OS ABI.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import secrets
import sys

from . import __version__
from .core import (NexusError, Recorder, active_mirrors, fetch_source, identifier, implementation_identity,
                   load_lock, load_target, write_json)
from .hakios import positive_seconds  # noqa: F401  (re-exported for compatibility)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TARGET = "qemu-virt-xnu"
# Statuses that mean "this operation did what it claims"; only run reports "passed".
SUCCESS = {"passed", "passed-display", "built-not-boot-tested", "prepared-not-compiled", "fetched-verified",
           "disk-prepared-not-boot-tested"}


@dataclass
class Context:
    root: Path
    work: Path
    target: dict
    target_path: Path
    sources: dict
    source: dict
    source_dir: Path
    record: Recorder
    args: argparse.Namespace


def recipe_for(target: dict):
    # Explicit reviewed modules, never a Python path or executable from a manifest.
    if target["recipe"] == "hakios-open":
        from . import hakios as recipe
    elif target["recipe"] == "ios-qemu":
        from . import iosqemu as recipe
    else:
        raise NexusError(f"Unknown recipe {target['recipe']!r}; implement and register a concrete recipe.")
    recipe.validate_target(target)
    return recipe


def target_file(value: str) -> Path:
    path = Path(value)
    if path.is_file():
        return path
    return ROOT / "targets" / identifier(value) / "target.toml"


def parser(recipe=None) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Celestia Nexus — reproducible Apple OS porting experiments",
                                epilog="Commands depend on --target; `./nexus --target ID --help` lists them.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--work", type=Path, default=ROOT / ".nexus", help="local state directory (default .nexus)")
    p.add_argument("--target", default=DEFAULT_TARGET, help="built-in target ID or external target.toml")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list built-in targets without downloading anything")
    sub.add_parser("status", help="show latest local build/run paths and durable development status")
    for name, help_text in (recipe.COMMANDS.items() if recipe else ()):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--json", action="store_true", help="print a machine-readable result")
        recipe.add_arguments(name, command)
    return p


def new_record(work: Path, operation: str, target: str) -> Recorder:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = work / "experiments" / f"{now}-{target}-{operation}-{secrets.token_hex(3)}"
    return Recorder(directory)


def latest_path(work: Path, target: str, kind: str) -> Path:
    return work / "latest" / f"{target}-{kind}.json"


def remember(work: Path, target: str, kind: str, file: Path):
    write_json(latest_path(work, target, kind), {"path": str(file.resolve())})


def latest(work: Path, target: str, kind: str) -> Path | None:
    index = latest_path(work, target, kind)
    return Path(json.loads(index.read_text())["path"]) if index.is_file() else None


def read_build(path: Path) -> dict:
    """Compatibility wrapper: the first recipe's build record reader."""
    from .hakios import read_build as hakios_read_build
    return hakios_read_build(path)


def selected_target(argv: list[str] | None) -> tuple[Path, dict | None, object | None]:
    """Find --target before the full parse so its recipe can declare commands."""
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--target", default=DEFAULT_TARGET)
    pre.add_argument("--work")
    known, rest = pre.parse_known_args(argv)
    if rest[:1] == ["list"]:
        return Path(), None, None
    path = target_file(known.target)
    target = load_target(path)
    return path, target, recipe_for(target)


def main(argv: list[str] | None = None) -> int:
    # SIGTERM/SIGHUP behave like Ctrl-C, so every recipe's cleanup runs.
    from .qemu import signals_as_interrupt
    with signals_as_interrupt():
        return _main(argv)


def _main(argv: list[str] | None) -> int:
    try:
        target_path, target, recipe = selected_target(argv)
    except NexusError as error:
        print(f"nexus: {error}", file=sys.stderr)
        return 1
    args = parser(recipe).parse_args(argv)
    record = None
    work = args.work.expanduser().resolve()
    try:
        if args.command == "list":
            for path in sorted((ROOT / "targets").glob("*/target.toml")):
                listed = load_target(path)
                recipe_for(listed)
                print(f"{listed['id']}: {listed['description']}")
            return 0
        if args.command == "analyze":
            return recipe.analyze_command(args)
        if args.command == "doctor":
            result = recipe.doctor(target, args)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                for item in result["checks"]:
                    print(f"{'OK' if item['ok'] else 'MISSING'} {item['name']}: {item['path'] or item['detail']}")
                print(recipe.READY if result["ready"] else recipe.SETUP_HINT)
            return 0 if result["ready"] else 1
        if args.command == "status":
            print("Project state: docs/status.md")
            kinds = ["build", "run"] + [kind for kind, _ in getattr(recipe, "EXTRA", {}).values()]
            for kind in kinds:
                path = latest(work, target["id"], kind)
                print(f"Latest {kind}: {path or 'none in this workspace'}")
            return 0
        sources = load_lock(ROOT / "upstreams.lock.toml")
        if target["source"] not in sources:
            raise NexusError(f"Target references missing upstream {target['source']}.")
        source = sources[target["source"]]
        if args.command == "smoke":
            result = recipe.doctor(target, args)
            if not result["ready"]:
                missing = ", ".join(item["name"] for item in result["checks"] if not item["ok"])
                raise NexusError(f"Host is missing {missing}; run ./nexus doctor before fetching/building.")
        work.mkdir(parents=True, exist_ok=True)
        record = new_record(work, args.command, target["id"])
        mirrors = active_mirrors(sources)
        operation = {"schema": 1, "operation": args.command, "target_path": str(target_path.resolve()),
                     "target": target, "mirrors": mirrors, "nexus_version": __version__,
                     "implementation": implementation_identity(), "python": platform.python_version()}
        write_json(record.directory / "operation.json", {**operation, "status": "running"})
        ctx = Context(ROOT, work, target, target_path, sources, source, work / "sources" / source["id"], record, args)
        if args.command in ("fetch", "smoke"):
            ctx.source_dir = fetch_source(work, source, record)
            result = {"source": source, "checkout": str(ctx.source_dir), "status": "fetched-verified"}
        if args.command in ("build", "smoke"):
            result = recipe.build_command(ctx)
            remember(work, target["id"], "build", record.directory / "build.json")
        if args.command in getattr(recipe, "EXTRA", {}):
            kind, function = recipe.EXTRA[args.command]
            result, file_name = function(ctx)
            remember(work, target["id"], kind, record.directory / file_name)
        if args.command in ("run", "smoke"):
            if args.command == "run":
                path = getattr(args, "build", None) or latest(work, target["id"], "build")
                if path is None:
                    raise NexusError("No previous build; run ./nexus smoke or ./nexus build.")
                result = recipe.read_build(path)
            if result["target"] != target["id"]:
                raise NexusError("Build belongs to a different target; rebuild for this target.")
            if result["inputs"]["target_configuration"] != target:
                raise NexusError("Target changed since this build; rebuild before running.")
            result = recipe.run_command(ctx, result)
            remember(work, target["id"], "run", record.directory / "result.json")
        write_json(record.directory / "operation.json", {**operation, "status": result["status"]})
        if args.json:
            print(json.dumps({"experiment": str(record.directory), **result}, indent=2))
        else:
            print(f"{result['status']}: {record.directory}")
            if "evidence" in result:
                print(result["evidence"]["diagnosis"])
        return 0 if result["status"] in SUCCESS else 1
    except (NexusError, OSError, ValueError) as error:
        if record:
            write_json(record.directory / "failure.json", {"status": "failed", "error": str(error), "operation": args.command})
            operation = json.loads((record.directory / "operation.json").read_text())
            write_json(record.directory / "operation.json", {**operation, "status": "failed", "error": str(error)})
        print(f"nexus: {error}" + (f"\nEvidence: {record.directory}" if record else ""), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        if record:
            write_json(record.directory / "failure.json", {"status": "interrupted", "operation": args.command})
            operation = json.loads((record.directory / "operation.json").read_text())
            write_json(record.directory / "operation.json", {**operation, "status": "interrupted"})
        print("nexus: interrupted; experiment logs preserved.", file=sys.stderr)
        return 130
