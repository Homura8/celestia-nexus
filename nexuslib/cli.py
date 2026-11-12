"""User commands; target-independent commands do not import a boot recipe."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import platform
import secrets
import sys

from . import __version__
from .core import NexusError, Recorder, fetch_source, implementation_identity, load_lock, load_target, write_json

ROOT = Path(__file__).resolve().parent.parent


def positive_seconds(value: str) -> float:
    n = float(value)
    if not math.isfinite(n) or not 0 < n <= 86400:
        raise argparse.ArgumentTypeError("timeout must be finite and in (0, 86400] seconds")
    return n


def port(value: str) -> int:
    n = int(value)
    if not 1 <= n <= 65535:
        raise argparse.ArgumentTypeError("port must be in 1..65535")
    return n


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Celestia Nexus — reproducible Apple OS porting experiments")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--work", type=Path, default=ROOT / ".nexus", help="local state directory (default .nexus)")
    p.add_argument("--target", default="qemu-virt-xnu", help="built-in target ID or external target.toml")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list built-in targets without downloading anything")
    for name in ("doctor", "fetch", "build", "prepare-kernel", "run", "smoke"):
        command = sub.add_parser(name, help={
            "doctor": "check host tools and firmware; make no changes",
            "fetch": "fetch and verify the target's exact upstream revision",
            "build": "build the loader and no-SDK Darwin probe (fetch first)",
            "prepare-kernel": "fetch Apple open sources, apply real patches and configure a QEMU kernel tree",
            "run": "boot a built target and record evidence",
            "smoke": "check, fetch, build and boot in one command",
        }[name])
        command.add_argument("--json", action="store_true", help="print a machine-readable result")
        if name in ("doctor", "build", "smoke"):
            command.add_argument("--loader", choices=("source", "prebuilt"), default="source")
        if name in ("build", "smoke"):
            command.add_argument("--kernel", type=Path, help="use a local ARM64 Mach-O kernel; hash it in build evidence")
        if name in ("run", "smoke", "doctor"):
            command.add_argument("--firmware", help="64 MiB non-Secure-Boot AArch64 pflash code")
            command.add_argument("--vars", help="matching 64 MiB pflash variables template")
        if name in ("run", "smoke"):
            command.add_argument("--timeout", type=positive_seconds, default=90)
            command.add_argument("--gdb-port", type=port, help="expose the guest GDB stub on loopback only")
        if name == "run":
            command.add_argument("--build", type=Path, help="build.json (default latest successful build for this target)")
    analysis = sub.add_parser("analyze", help="analyze a saved serial log; no QEMU needed")
    analysis.add_argument("log", type=Path)
    analysis.add_argument("--token", help="expected token from the run's inputs.json/result.json")
    analysis.add_argument("--json", action="store_true")
    sub.add_parser("status", help="show latest local build/run paths and durable development status")
    return p


def new_record(work: Path, operation: str, target: str) -> Recorder:
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    directory = work / "experiments" / f"{now}-{target}-{operation}-{secrets.token_hex(3)}"
    return Recorder(directory)


def latest_path(work: Path, target: str, kind: str) -> Path:
    return work / "latest" / f"{target}-{kind}.json"


def recipe_for(target: dict):
    # Explicit reviewed modules, never a Python path or executable from a manifest.
    if target["recipe"] == "hakios-open":
        from . import hakios
        hakios.validate_target(target)
        return hakios
    raise NexusError(f"Unknown recipe {target['recipe']!r}; implement and register a concrete recipe.")


def remember(work: Path, target: str, kind: str, file: Path):
    write_json(latest_path(work, target, kind), {"path": str(file.resolve())})


def read_build(path: Path) -> dict:
    try:
        result = json.loads(path.read_text())
        if (result["schema"] != 1 or set(result["artifacts"]) != {"kernel", "probe", "loader.efi"}
                or result["loader_mode"] not in ("source", "prebuilt")
                or not isinstance(result["inputs"]["target_configuration"], dict)):
            raise ValueError("unsupported build record")
        for item in result["artifacts"].values():
            if not isinstance(item["path"], str) or not isinstance(item["sha256"], str) or len(item["sha256"]) != 64:
                raise ValueError("invalid artifact record")
        return result
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NexusError(f"Cannot read build record {path}: {error}; run ./nexus build first.") from error


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    record = None
    work = args.work.expanduser().resolve()
    try:
        if args.command == "list":
            for path in sorted((ROOT / "targets").glob("*/target.toml")):
                target = load_target(path)
                recipe_for(target)
                print(f"{target['id']}: {target['description']}")
            return 0
        if args.command == "analyze":
            from .qemu import analyze, MAX_LOG
            if args.log.stat().st_size > MAX_LOG:
                raise NexusError("Log is larger than the 16 MiB analysis limit.")
            result = analyze(args.log.read_text(errors="replace"), args.token)
            print(json.dumps(result, indent=2) if args.json else result["diagnosis"])
            return 0 if result["passed"] else 1
        target_path = Path(args.target)
        if not target_path.is_file():
            from .core import identifier
            target_path = ROOT / "targets" / identifier(args.target) / "target.toml"
        target = load_target(target_path)
        recipe = recipe_for(target)
        if args.command == "doctor":
            result = recipe.doctor(args.firmware, args.vars, args.loader)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                for item in result["checks"]:
                    print(f"{'OK' if item['ok'] else 'MISSING'} {item['name']}: {item['path'] or item['detail']}")
                print("Ready for an open XNU probe." if result["ready"] else "Follow docs/development.md#host-setup, then run doctor again.")
            return 0 if result["ready"] else 1
        if args.command == "status":
            print("Project state: docs/status.md")
            for kind in ("build", "run", "kernel"):
                index = latest_path(work, target["id"], kind)
                print(f"Latest {kind}: {json.loads(index.read_text())['path'] if index.exists() else 'none in this workspace'}")
            return 0
        sources = load_lock(ROOT / "upstreams.lock.toml")
        if target["source"] not in sources:
            raise NexusError(f"Target references missing upstream {target['source']}.")
        source = sources[target["source"]]
        if args.command == "smoke":
            result = recipe.doctor(args.firmware, args.vars, args.loader)
            if not result["ready"]:
                missing = ", ".join(item["name"] for item in result["checks"] if not item["ok"])
                raise NexusError(f"Host is missing {missing}; run ./nexus doctor before fetching/building.")
        work.mkdir(parents=True, exist_ok=True)
        record = new_record(work, args.command, target["id"])
        write_json(record.directory / "operation.json", {"schema": 1, "operation": args.command,
                   "target_path": str(target_path.resolve()), "target": target,
                   "nexus_version": __version__, "implementation": implementation_identity(),
                   "python": platform.python_version(), "status": "running"})
        source_dir = work / "sources" / source["id"]
        if args.command in ("fetch", "smoke"):
            source_dir = fetch_source(work, source, record)
            result = {"source": source, "checkout": str(source_dir), "status": "fetched-verified"}
        if args.command in ("build", "smoke"):
            result = recipe.build(ROOT, source_dir, source, target, record, args.loader, args.kernel)
            remember(work, target["id"], "build", record.directory / "build.json")
        if args.command == "prepare-kernel":
            result = recipe.prepare_kernel(work, sources, target, record)
            remember(work, target["id"], "kernel", record.directory / "prepared.json")
        if args.command in ("run", "smoke"):
            if args.command == "run":
                path = args.build
                if path is None:
                    index = latest_path(work, target["id"], "build")
                    if not index.is_file():
                        raise NexusError("No previous build; run ./nexus smoke or ./nexus build.")
                    path = Path(json.loads(index.read_text())["path"])
                result = read_build(path)
            if result["target"] != target["id"]:
                raise NexusError("Build belongs to a different target; rebuild for this target.")
            if result["inputs"]["target_configuration"] != target:
                raise NexusError("Target changed since this build; rebuild before running.")
            result = recipe.run(target, result, record, timeout=args.timeout, code=args.firmware,
                         variables=args.vars, gdb_port=args.gdb_port)
            remember(work, target["id"], "run", record.directory / "result.json")
        write_json(record.directory / "operation.json", {"schema": 1, "status": result["status"],
                   "operation": args.command, "target": target, "target_path": str(target_path.resolve()),
                   "nexus_version": __version__, "implementation": implementation_identity(),
                   "python": platform.python_version()})
        if args.json:
            print(json.dumps({"experiment": str(record.directory), **result}, indent=2))
        else:
            print(f"{result['status']}: {record.directory}")
            if "evidence" in result:
                print(result["evidence"]["diagnosis"])
        return 0 if result["status"] in ("passed", "built-not-boot-tested", "prepared-not-compiled", "fetched-verified") else 1
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
