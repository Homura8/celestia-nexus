"""Recipe `hakios-open`: HakiOS open XNU + UEFI loader + original syscall probe.

HakiOS conventions (XNUP payload at 0xF0000000, loader banner, probe checks,
pflash firmware) stay in this module; the CLI and qemu.py know none of them.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time

from .core import (NexusError, Recorder, digest, fetch_source, implementation_identity, relative_path,
                   verify_source, verified_artifact, write_json)
from .formats import macho_info, payload_pack, static_entry
from .host import file_record, require_tools, version
from .host import doctor as host_doctor
from .qemu import MAX_LOG, QMP, deferred_signals, qemu_path, stop


COMMANDS = {
    "doctor": "check host tools and firmware; make no changes",
    "fetch": "fetch and verify the target's exact upstream revision",
    "build": "build the loader and no-SDK Darwin probe (fetch first)",
    "prepare-kernel": "fetch Apple open sources, apply real patches and configure a QEMU kernel tree",
    "run": "boot a built target and record evidence",
    "smoke": "check, fetch, build and boot in one command",
    "analyze": "analyze a saved serial log; no QEMU needed",
}
SETUP_HINT = "Follow docs/development.md#host-setup, then run doctor again."
READY = "Ready for an open XNU probe."
SCOPE = "open-xnu-userspace-probe"


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


def add_arguments(name: str, command: argparse.ArgumentParser) -> None:
    if name == "analyze":
        command.add_argument("log", type=Path)
        command.add_argument("--token", help="expected token from the run's inputs.json/result.json")
        return
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


def doctor(target: dict, args: argparse.Namespace) -> dict:
    return host_doctor(getattr(args, "firmware", None), getattr(args, "vars", None),
                       getattr(args, "loader", "source"), clock=target["qemu"]["clock"])


def build_command(ctx) -> dict:
    return build(ctx.root, ctx.source_dir, ctx.source, ctx.target, ctx.record, ctx.args.loader, ctx.args.kernel)


def run_command(ctx, build_record: dict) -> dict:
    return run(ctx.target, build_record, ctx.record, timeout=ctx.args.timeout, code=ctx.args.firmware,
               variables=ctx.args.vars, gdb_port=ctx.args.gdb_port)


def prepare_kernel_command(ctx) -> tuple[dict, str]:
    return prepare_kernel(ctx.work, ctx.sources, ctx.target, ctx.record), "prepared.json"


EXTRA = {"prepare-kernel": ("kernel", prepare_kernel_command)}


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


def analyze_command(args: argparse.Namespace) -> int:
    if args.log.stat().st_size > MAX_LOG:
        raise NexusError("Log is larger than the 16 MiB analysis limit.")
    result = analyze(args.log.read_text(errors="replace"), args.token)
    print(json.dumps(result, indent=2) if args.json else result["diagnosis"])
    return 0 if result["passed"] else 1


def validate_target(target: dict) -> None:
    """Recipe constraints belong here, not in the shared target reader."""
    try:
        extra = set(target) - {"schema", "id", "description", "architecture", "recipe", "source", "kernel", "loader", "qemu"}
        if extra:
            raise NexusError(f"Unknown HakiOS target fields: {sorted(extra)}")
        if target["architecture"] != "aarch64" or target["source"] != "hakios":
            raise NexusError("This recipe is reviewed for the pinned HakiOS AArch64 source only.")
        for name in ("kernel", "loader"):
            item = target[name]
            if set(item) != {"path", "sha256"}:
                raise NexusError(f"{name}: expected path and sha256 only.")
            relative_path(item["path"])
            if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise NexusError(f"{name}.sha256 must be a full SHA-256.")
        qemu = target["qemu"]
        if set(qemu) != {"accel", "clock", "memory_mib", "cpus", "machine", "cpu"}:
            raise NexusError("Unknown/missing QEMU settings; see targets/qemu-virt-xnu/target.toml.")
        if qemu["accel"] != "tcg":
            raise NexusError("This recipe validates TCG only; do not silently substitute HVF/KVM.")
        if qemu["clock"] not in ("instruction", "host"):
            raise NexusError("This recipe supports instruction or host clock only.")
        if type(qemu["memory_mib"]) is not int or not 4096 <= qemu["memory_mib"] <= 8192:
            raise NexusError("HakiOS open needs 4096..8192 MiB for this payload address.")
        if type(qemu["cpus"]) is not int or qemu["cpus"] != 1:
            raise NexusError("This recipe validates one CPU.")
        if qemu["machine"] != "virt,gic-version=3" or qemu["cpu"] != "cortex-a76":
            raise NexusError("This recipe validates virt/GICv3 with cortex-a76.")
    except (KeyError, TypeError) as error:
        raise NexusError(f"Malformed HakiOS target: {error}") from error


def build(root: Path, source_dir: Path, source: dict, target: dict,
          record: Recorder, loader: str = "source", kernel: Path | None = None) -> dict:
    verify_source(source_dir, source)
    needed = ("clang", "ld64") + (("lld_link",) if loader == "source" else ())
    found = require_tools(needed)
    out = record.directory
    kernel_path = kernel.resolve() if kernel else verified_artifact(source_dir, target["kernel"])
    if not kernel_path.is_file():
        raise NexusError(f"No kernel: {kernel_path}")
    kernel_info = macho_info(kernel_path.read_bytes())
    shutil.copyfile(kernel_path, out / "kernel")
    compile_command = [found["clang"], "--target=arm64-apple-macos11", "-Os", "-ffreestanding",
                       "-fno-builtin", "-fno-stack-protector", "-fno-asynchronous-unwind-tables",
                       "-Wall", "-Wextra", "-Werror", "-c", str(root / "guest/probe.c"), "-o", "probe.o"]
    record.command(compile_command, cwd=out)
    record.command([found["ld64"], "-arch", "arm64", "-platform_version", "macos", "11.0", "11.0",
                    "-e", "_start", "-no_uuid", "-no_adhoc_codesign", "-no_fixup_chains",
                    "-headerpad", "0x1000", "-pagezero_size", "0x100000000",
                    "-o", "probe.linked", "probe.o"], cwd=out)
    (out / "probe").write_bytes(static_entry((out / "probe.linked").read_bytes()))
    if loader == "source":
        # These reviewed files contain the freestanding loader; no upstream setup.sh.
        loader_dir = out / "loader-source"
        loader_dir.mkdir()
        for name in ("loader.c", "efi.h", "mkidentity.py"):
            shutil.copyfile(source_dir / "xnuloader" / name, loader_dir / name)
        record.command([sys.executable, str(loader_dir / "mkidentity.py"), "--placeholder"],
                       cwd=out, output=loader_dir / "identity.h")
        record.command([found["clang"], "--target=aarch64-unknown-windows", "-ffreestanding",
                        "-fno-builtin", "-fno-stack-protector", "-fshort-wchar", "-mgeneral-regs-only",
                        "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter", "-c",
                        str(loader_dir / "loader.c"), "-o", "loader.obj"], cwd=out)
        record.command([found["lld_link"], "/subsystem:efi_application", "/entry:efi_main",
                        "/nodefaultlib", "/base:0xA1000000", "/timestamp:0", "/out:loader.efi", "loader.obj"], cwd=out)
    else:
        shutil.copyfile(verified_artifact(source_dir, target["loader"]), out / "loader.efi")
    artifacts = {name: file_record(out / name) for name in ("kernel", "probe", "loader.efi")}
    result = {"schema": 1, "status": "built-not-boot-tested", "target": target["id"],
              "source": source, "loader_mode": loader,
              "kernel_origin": "user-supplied" if kernel else "upstream-prebuilt",
              "kernel_source_correspondence": "not independently verified",
              "implementation": implementation_identity(),
              "inputs": {"probe_source": file_record(root / "guest/probe.c"),
                         "target_configuration": target},
              "tool_versions": {name: version(found[name]) for name in needed},
              "artifacts": artifacts, "kernel_info": kernel_info,
              "probe_info": macho_info((out / "probe").read_bytes())}
    write_json(out / "build.json", result)
    return result


def copy_source(source: Path, destination: Path, boundary: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise NexusError(f"Expected a regular source file: {source}")
    if not destination.resolve().is_relative_to(boundary.resolve()):
        raise NexusError(f"Source overlay escapes the prepared tree: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def prepare_kernel(work: Path, sources: dict, target: dict, record: Recorder) -> dict:
    """Materialize and check the real XNU/HFS patch series without an Apple SDK.

    Use reviewed source transformations, not upstream's network/setup scripts.
    Every attempt gets a new tree; an earlier edited experiment is never reset.
    """
    upstream = fetch_source(work, sources[target["source"]], record)
    xnu = fetch_source(work, sources["apple-xnu"], record)
    hfs = fetch_source(work, sources["apple-hfs"], record)
    tree = record.directory / "kernel-source"
    record.command(["git", "clone", "--no-hardlinks", "--no-checkout", str(xnu), str(tree)], cwd=work)
    record.command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(tree), "checkout",
                    "--detach", sources["apple-xnu"]["commit"]], cwd=work)
    patch = upstream / "xnu/hakios.patch"
    record.command(["git", "-C", str(tree), "apply", "--check", "--whitespace=nowarn", str(patch)], cwd=work)
    record.command(["git", "-C", str(tree), "apply", "--whitespace=nowarn", str(patch)], cwd=work)
    copied = {}
    overlay = upstream / "xnu/files"
    for path in sorted(overlay.rglob("*")):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(overlay)
            copy_source(path, tree / relative, tree)
            copied[str(relative)] = digest(path)
    for listing, source_subdir, target_subdir in (("core.list", "core", "bsd/hfs"),
                                                 ("encodings.list", "hfs_encodings", "bsd/hfs_encodings")):
        for line in (upstream / "xnu/hfs" / listing).read_text().splitlines():
            name = relative_path(line.strip())
            path = hfs / source_subdir / name
            destination = Path(target_subdir) / name
            copy_source(path, tree / destination, tree)
            copied[str(destination)] = digest(path)
    hfs_patch = upstream / "xnu/hfs/hfs.patch"
    record.command(["git", "-C", str(tree), "apply", "--check", str(hfs_patch)], cwd=work)
    record.command(["git", "-C", str(tree), "apply", str(hfs_patch)], cwd=work)
    for line in (upstream / "drivers/map").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        subsystem, destination = line.split()
        relative = relative_path(destination)
        path = upstream / "drivers" / relative_path(subsystem) / relative.name
        copy_source(path, tree / relative, tree)
        copied[str(relative)] = digest(path)
    configuration = record.directory / "qemu.config"
    config_tool = upstream / "tools/hakios-config.py"
    record.command([sys.executable, str(config_tool), "defconfig", "qemu", "-o", str(configuration)], cwd=upstream)
    record.command([sys.executable, str(config_tool), "kernel", "--config", str(configuration),
                    "--tree", str(tree)], cwd=upstream)
    record.command(["git", "-C", str(tree), "diff", "--check"], cwd=work)
    names = record.command(["git", "-C", str(tree), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=work)
    inventory = {name: digest(tree / name) for name in names.split("\0") if name}
    write_json(record.directory / "tree-manifest.json", inventory)
    for key in (target["source"], "apple-xnu", "apple-hfs"):
        verify_source(work / "sources" / key, sources[key])
    result = {"schema": 1, "status": "prepared-not-compiled", "target": target["id"], "tree": str(tree),
              "sources": {key: sources[key] for key in (target["source"], "apple-xnu", "apple-hfs")},
              "patches": [file_record(patch), file_record(hfs_patch)], "configuration": file_record(configuration),
              "overlay_inputs": copied, "tree_manifest": file_record(record.directory / "tree-manifest.json"),
              "next": "Review the prepared tree; supply an authorised SDK/toolchain before compilation. See docs/development.md#kernel-source."}
    write_json(record.directory / "prepared.json", result)
    return result


# Boot contract: XNUP payload, loader banner stages and probe checks.

CHECKS = ("console", "pid1", "uid0", "sysctl", "boot-token", "errno", "mmap-rw", "mprotect", "munmap", "timer")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b=[0-9]*[a-z]?")
PANIC = re.compile(r"panic\(cpu |^panic:|Kernel panic|^NEXUS (?:CHECK \S+|RESULT) FAIL", re.MULTILINE)
STAGES = (
    ("loader", r"^== XNULOADER v3 ==$"),
    ("kernel", r"^Darwin Kernel Version [0-9].*$"),
    ("root", r"^BSD root: md0,.*$"),
    ("userspace", r"^NEXUS PROBE 1$"),
)
# Printed by AAVMF/EDK2 before boot device selection; diagnostic only, not a stage.
FIRMWARE = re.compile(r"^UEFI firmware \(version", re.MULTILINE)


def analyze(text: str, token: str | None) -> dict:
    """A complete pass needs ordered boot stages, checks, nonce and liveness.

    This is regression evidence from a cooperative research guest, not attestation
    against a malicious guest. A panic anywhere invalidates all earlier success.
    """
    text = ANSI.sub("", text).replace("\r", "")
    rejected = PANIC.search(text)
    stages = []
    cursor = 0
    for name, pattern in STAGES:
        match = re.compile(pattern, re.MULTILINE).search(text, cursor)
        if not match:
            break
        stages.append(name)
        cursor = match.end()
    checks = []
    if len(stages) == len(STAGES):
        for name in CHECKS:
            match = re.compile(r"^NEXUS CHECK " + re.escape(name) + r" PASS$", re.MULTILINE).search(text, cursor)
            if not match:
                break
            checks.append(name)
            cursor = match.end()
    result_match = None
    if token and re.fullmatch(r"[0-9a-f]{32}", token) and len(checks) == len(CHECKS):
        result_match = re.compile(r"^NEXUS RESULT PASS token=" + token + r"$", re.MULTILINE).search(text, cursor)
    heartbeats = len(re.findall(r"^NEXUS HEARTBEAT$", text[result_match.end():], re.MULTILINE)) if result_match else 0
    passed = bool(result_match and heartbeats >= 2 and not rejected)
    if rejected:
        hint = "Guest panic or explicit probe failure; inspect serial.log and diagnostics.json."
    elif not stages and FIRMWARE.search(text):
        hint = ("Firmware started but never reached the loader. A single occurrence matches the known "
                "intermittent UEFI stall (docs/status.md): keep this experiment and rerun ./nexus run "
                "with the same build. If it repeats, check the firmware pair, ESP and boot device.")
    elif not stages:
        hint = "No loader: check firmware pair, ESP, QEMU stderr and the boot device."
    elif stages[-1] == "loader":
        hint = "Loader reached; inspect Mach-O loading, memory layout and the kernel handoff."
    elif stages[-1] == "kernel":
        hint = "Kernel reached; inspect interrupts, ramdisk and root mount."
    elif stages[-1] == "root":
        hint = "Root mounted; inspect static Mach-O entry, signing policy and PID 1 launch."
    elif not token:
        hint = "Supply the run's expected token to validate its result; text alone is not a certified run."
    elif len(checks) != len(CHECKS):
        hint = "Userspace reached; first incomplete check: " + CHECKS[len(checks)]
    elif not result_match:
        hint = "Checks seen, but no result with this run's token."
    elif heartbeats < 2:
        hint = "Result seen; waiting for two subsequent heartbeats and no panic."
    else:
        hint = "Open XNU userspace probe passed; this does not establish an iOS/userland/GUI boot."
    return {"passed": passed, "stages": stages, "checks": checks, "heartbeat_count": heartbeats,
            "rejection": rejected.group(0) if rejected else None, "diagnosis": hint}


def run(target: dict, build: dict, record: Recorder, *, timeout: float = 90,
        code: str | None = None, variables: str | None = None, gdb_port: int | None = None) -> dict:
    environment = host_doctor(code, variables, loader=build["loader_mode"], runtime_only=True,
                         clock=target["qemu"]["clock"])
    if not environment["ready"]:
        failures = "; ".join(item["name"] + ": " + item["detail"] for item in environment["checks"] if not item["ok"])
        raise NexusError("Host is not ready: " + failures)
    out = record.directory
    token = secrets.token_hex(16)
    for name, item in build["artifacts"].items():
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise NexusError(f"Built artifact changed/missing: {name}; rebuild before running.")
    esp = out / "esp/EFI/BOOT"
    esp.mkdir(parents=True)
    shutil.copyfile(build["artifacts"]["loader.efi"]["path"], esp / "BOOTAA64.EFI")
    # Fresh variable storage every run: the host firmware/template is never writable.
    shutil.copyfile(environment["variables"], out / "vars.fd")
    bootargs = "cpus=1 nexus_token=" + token
    (out / "payload.bin").write_bytes(payload_pack({
        "kernel": Path(build["artifacts"]["kernel"]["path"]).read_bytes(),
        "ramdisk": Path(build["artifacts"]["probe"]["path"]).read_bytes(),
        "cmdline": bootargs.encode() + b"\0",
    }))
    write_json(out / "inputs.json", {
        "schema": 1, "target": target, "build": build, "expected_token": token,
        "implementation": implementation_identity(),
        "host": environment, "firmware": file_record(Path(environment["firmware"])),
        "variables_template": file_record(Path(environment["variables"])),
        "payload": file_record(out / "payload.bin"),
    })
    q = target["qemu"]
    argv = [environment["tools"]["qemu"], "-M", q["machine"], "-cpu", q["cpu"],
            "-smp", str(q["cpus"]), "-m", str(q["memory_mib"]), "-accel", "tcg,thread=single,tb-size=384",
            "-drive", "if=pflash,format=raw,readonly=on,file=" + qemu_path(Path(environment["firmware"])),
            "-drive", "if=pflash,format=raw,file=vars.fd",
            "-drive", "file=fat:ro:esp,format=raw,if=virtio,readonly=on",
            "-device", "loader,file=payload.bin,addr=0xF0000000,force-raw=on",
            "-display", "none", "-serial", "file:serial.log", "-monitor", "none", "-no-reboot",
            "-nic", "none", "-qmp", "stdio"]
    if q["clock"] == "instruction":
        argv += ["-icount", "shift=3,align=off,sleep=off"]
    if gdb_port:
        argv += ["-gdb", f"tcp:127.0.0.1:{gdb_port}"]
    write_json(out / "command.json", {"argv": argv, "cwd": str(out)})
    started = time.monotonic()
    qmp = None
    process = None
    status = "failed"
    details = analyze("", token)
    diagnostic = {}
    stage_seconds = {}
    interruption = None
    try:
        with (out / "qemu.log").open("wb") as log:
            process = subprocess.Popen(argv, cwd=out, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=log, start_new_session=True, bufsize=0)
            qmp = QMP(process.stdout, process.stdin)
            while True:
                elapsed = time.monotonic() - started
                serial = out / "serial.log"
                if serial.exists():
                    if serial.stat().st_size > MAX_LOG:
                        details["diagnosis"] = "Serial output exceeded 16 MiB; stopped a runaway experiment."
                        break
                    details = analyze(serial.read_text(errors="replace"), token)
                    for name in details["stages"]:
                        # Polled every 0.1 s: when each stage was first seen, for stall analysis.
                        stage_seconds.setdefault(name, round(elapsed, 1))
                if details["rejection"]:
                    break
                if process.poll() is not None:
                    details["diagnosis"] = f"QEMU exited unexpectedly ({process.returncode}). " + details["diagnosis"]
                    break
                if details["passed"]:
                    status = "passed"
                    break
                if elapsed >= timeout:
                    status = "timed-out"
                    break
                time.sleep(0.1)
    except KeyboardInterrupt:
        status = "interrupted"
        interruption = True
    except (OSError, NexusError, TimeoutError) as error:
        details["diagnosis"] = f"Cannot start/operate QEMU: {error}"
    finally:
        # Bounded (QMP 2 s per command, stop() at most 9 s); a second Ctrl-C cannot abort it.
        with deferred_signals() as late:
            if qmp:
                for name, arguments in (("query-status", None), ("query-cpus-fast", None),
                                        ("human-monitor-command", {"command-line": "info registers"})):
                    try:
                        diagnostic[name] = qmp.command(name, arguments)
                    except (OSError, NexusError, TimeoutError) as error:
                        diagnostic[name] = {"error": str(error)}
            shutdown = stop(process, qmp) if process else "not-started"
            if status == "passed" and (shutdown != "qmp-quit" or process.returncode != 0):
                status = "failed"
                details["diagnosis"] = "Guest checks passed, but QEMU did not stop cleanly through QMP."
            if qmp:
                qmp.close()
            # Re-read after shutdown: a late panic must invalidate an earlier pass.
            serial = out / "serial.log"
            if serial.exists() and serial.stat().st_size <= MAX_LOG:
                final = analyze(serial.read_text(errors="replace"), token)
                if final["rejection"] or (status == "passed" and not final["passed"]):
                    status = "failed"
                if status == "passed" or final["rejection"]:
                    details = final
            write_json(out / "diagnostics.json", diagnostic)
            result = {"schema": 1, "status": status, "target": target["id"], "expected_token": token,
                      "implementation": implementation_identity(), "shutdown": shutdown,
                      "duration_seconds": round(time.monotonic() - started, 3),
                      "stage_seconds": stage_seconds,
                      "qemu_returncode": process.returncode if process else None,
                      "evidence": details, "serial": file_record(serial) if serial.exists() else None,
                      "build_record": build, "scope": "open-xnu-userspace-probe"}
            write_json(out / "result.json", result)
        interruption = interruption or bool(late)
    if interruption:
        raise KeyboardInterrupt
    return result
