"""Recipe `ios-qemu`: reproduce lgrachov/ios-qemu's stock iOS 16.7.16 userland boot.

Upstream's build boundary is kept: its CI-built kernel, its device-tree and
payload generators, its root-disk builder and its QEMU launcher run unmodified
from the pinned checkout (copied, hashed). Nexus adds what upstream leaves to a
human: verified inputs, a disposable per-run disk clone, a live kernel log,
independent ordered milestones, scripted interaction and a durable record.

Milestones are never promoted: kernel -> root -> launchd -> backboardd +
springboard (kernel log), then display (framebuffer contents), then
interaction (an app process started by injected touch input).
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import time
import zlib

from . import ipsw
from .core import (NexusError, Recorder, digest, git, implementation_identity, relative_path, verify_source,
                   write_json)
from .host import file_record, version
from .qemu import MAX_LOG, QMP, alive, deferred_signals, processes, wait_gone

COMMANDS = {
    "doctor": "check Apple Silicon/HVF, QEMU, clang and disk tools; make no changes",
    "fetch": "fetch and verify the pinned ios-qemu revision",
    "build": "fetch the pinned upstream CI kernel (or --kernel) and stage upstream boot tools",
    "prepare-disk": "verify your IPSW and build the iOS root disk (asks for sudo once)",
    "run": "boot a fresh clone of the prepared disk and record milestone evidence",
    "smoke": "doctor, fetch, build and run with the latest prepared disk",
    "analyze": "classify a saved kernel.log without QEMU",
}
SETUP_HINT = "Follow docs/ios-qemu.md#host-setup, then run doctor again."
READY = "Ready to run ios-qemu (prepare-disk also needs the disk-tool checks)."
SCOPE = "ios-userland-gui-interaction"

BOOT_TOOLS = ("adt.py", "mkadt.py", "mkpayload.py", "qemu-sweet.py", "qemu-ramfb-stub.S", "qemu-touch.py")
DISK_TOOLS = ("mkiosroot-mac.sh", "sweet-root-tweaks.py", "mkufsdisk.py")
# harness.sh --ios boot-args at the pinned commit; cpus= follows the target.
BOOTARGS = ("debug=0xc serial=3 cpus={cpus} keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 "
            "unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 "
            "launchd_unsecure_cache=1 wdt=-1 sweetfb_noconsole=1 sweetfb_hz=30 sweetvinput=1 sweetvnet=1 "
            "sweettouch=0 ml-timeout-global-scale=20")
ADT_ARGS = ("--hvf", "--qemu-ufs", "--qemu-fullfb", "--highmem")
FB_BASE, FB_W, FB_H = 0x9C000000, 1125, 2436       # qemu-sweet.py --fullfb
# Safari in the default iPhone X dock (Phone, Safari, Messages, Music), measured on
# this recipe's home screen; upstream README's (561, 2259) hits the gap after it.
SAFARI = (433, 2267)
UNRESPONSIVE = 30                                   # seconds of failed QMP reads before giving up                                # README: Safari in the dock
# Kernel message-buffer lines carry a "[   12.345678]: " prefix.
LINE = r"^(?:\[\s*\d+\.\d+\]: )?"
# Ordered chain; then backboardd and SpringBoard, which launchd starts in either order.
MILESTONES = (
    ("kernel", LINE + r"Darwin Kernel Version \d"),
    ("root", LINE + r"BSD root: ufsroot0"),
    ("launchd", LINE + r"exec launchd$"),
)
AFTER_LAUNCHD = (("backboardd", LINE + r"exec backboardd$"), ("springboard", LINE + r"exec SpringBoard$"))
ALL_MILESTONES = tuple(name for name, _ in MILESTONES + AFTER_LAUNCHD)
GUI = ("display", "interaction")
PANIC = re.compile(r"panic\(cpu |SWEET EARLY PANIC", re.MULTILINE)
CRASH = re.compile(LINE + r"CRASH (\S+?)\[\d+\]", re.MULTILINE)
EXEC = re.compile(LINE + r"exec (\S+)$", re.MULTILINE)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


# --- arguments and target ---------------------------------------------------

def seconds(value: str) -> float:
    n = float(value)
    if not math.isfinite(n) or not 0 < n <= 86400:
        raise argparse.ArgumentTypeError("seconds must be finite and in (0, 86400]")
    return n


def add_arguments(name: str, command: argparse.ArgumentParser) -> None:
    if name == "analyze":
        command.add_argument("log", type=Path, help="kernel.log from a run")
    if name in ("build", "smoke"):
        command.add_argument("--kernel", type=Path,
                             help="use a local kernel.development.sweet instead of the pinned CI artifact")
    if name == "prepare-disk":
        command.add_argument("--ipsw", type=Path, required=True, help="your iPhone X 16.7.16 (20H392) IPSW")
        command.add_argument("--keep-inputs", action="store_true",
                             help="keep the extracted OS/cryptex DMGs and root.hfs (about 20 GB)")
    if name in ("run", "smoke"):
        command.add_argument("--disk", type=Path, help="disk.json from prepare-disk, or a previous run's "
                             "result.json to continue from its disk (default: latest prepared disk)")
        command.add_argument("--timeout", type=seconds, default=900, help="overall limit (default 900 s)")
        command.add_argument("--settle", type=seconds, default=60,
                             help="wait after SpringBoard starts before checking the screen (default 60 s)")
        command.add_argument("--no-interact", action="store_true", help="skip the scripted unlock/app launch")
        command.add_argument("--hold", type=seconds, help="keep the guest running this long after the checks")
        command.add_argument("--display", action="store_true", help="show the QEMU window (Cocoa)")
        command.add_argument("--audio", action="store_true", help="virtio-sound to CoreAudio (sweetvsnd=1)")
    if name == "run":
        command.add_argument("--build", type=Path, help="build.json (default latest build for this target)")


def validate_target(target: dict) -> None:
    try:
        extra = set(target) - {"schema", "id", "description", "architecture", "recipe", "source",
                               "source_check", "kernel", "ipsw", "qemu"}
        if extra:
            raise NexusError(f"Unknown ios-qemu target fields: {sorted(extra)}")
        if target["architecture"] != "aarch64" or target["source"] != "ios-qemu":
            raise NexusError("This recipe is reviewed for the pinned ios-qemu AArch64 source only.")
        check = target["source_check"]
        if set(check) != {"patches_tree", "workflow_blob"} or not all(
                re.fullmatch(r"[0-9a-f]{40}", value) for value in check.values()):
            raise NexusError("source_check needs patches_tree and workflow_blob Git object IDs.")
        kernel = target["kernel"]
        if set(kernel) != {"repository", "run_id", "run_commit", "artifact", "artifact_sha256", "member",
                           "sha256", "expires"}:
            raise NexusError("kernel: unexpected or missing fields; see targets/ios-qemu-iphonex/target.toml.")
        if not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", kernel["repository"]) or type(kernel["run_id"]) is not int:
            raise NexusError("kernel.repository must be owner/name and run_id an integer.")
        relative_path(kernel["member"])
        for key in ("sha256", "artifact_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", kernel[key]):
                raise NexusError(f"kernel.{key} must be a full SHA-256.")
        image = target["ipsw"]
        if set(image) != {"file", "sha256", "product_version", "build", "product_type", "board",
                          "device_tree_sha256", "disk_size"}:
            raise NexusError("ipsw: unexpected or missing fields.")
        if not re.fullmatch(r"\d+g", image["disk_size"]):
            raise NexusError("ipsw.disk_size must look like 16g.")
        qemu = target["qemu"]
        if set(qemu) != {"accel", "cpus"} or qemu["accel"] != "hvf":
            raise NexusError("This recipe reproduces upstream's HVF path only; TCG is unvalidated.")
        if type(qemu["cpus"]) is not int or not 1 <= qemu["cpus"] <= 8:
            raise NexusError("qemu.cpus must be 1..8.")
    except (KeyError, TypeError) as error:
        raise NexusError(f"Malformed ios-qemu target: {error}") from error


# --- host checks -------------------------------------------------------------

def which(name: str, *extra: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for directory in extra:
        if (Path(directory) / name).is_file():
            return str(Path(directory) / name)
    return None


def gnu_rsync() -> str | None:
    # mkiosroot-mac.sh hard-codes Homebrew's GNU rsync paths.
    for path in ("/opt/homebrew/bin/rsync", "/usr/local/bin/rsync"):
        if Path(path).is_file():
            return path
    return None


def doctor(target: dict, args: argparse.Namespace | None = None) -> dict:
    darwin = platform.system() == "Darwin"
    checks = []

    def add(name, ok, path=None, detail="", needed_for="run"):
        checks.append({"name": name, "ok": bool(ok), "path": path, "detail": detail, "needed_for": needed_for})

    add("host", darwin and platform.machine() == "arm64", None,
        platform.platform() + "; upstream's --ios path needs macOS on Apple Silicon (HVF)")
    memory = 0
    if darwin:
        try:
            memory = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
                                        timeout=10).stdout.strip() or 0)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            memory = 0
    add("memory", memory >= 16 * 1024**3, None, f"{memory / 1024**3:.0f} GiB; the guest is given 7 GiB, 16 GiB host minimum")
    qemu = which("qemu-system-aarch64")
    detail, hvf = "missing; brew install qemu", False
    if qemu:
        try:
            detail = version(qemu)
            hvf = "hvf" in subprocess.run([qemu, "-accel", "help"], capture_output=True, text=True, timeout=20).stdout
        except (NexusError, OSError, subprocess.TimeoutExpired) as error:
            detail = str(error)
    add("qemu", qemu and hvf, qemu, detail + ("" if hvf else "; HVF accelerator not available"))
    clang = which("clang")
    add("clang", clang, clang, "assembles upstream's boot stub (Xcode command-line tools)")
    gh = which("gh")
    add("gh", True, gh, "downloads the pinned CI kernel (needs `gh auth login`); not needed with --kernel or a cached kernel"
        if gh else "missing: only needed to download the pinned CI kernel; brew install gh", "build")
    rsync = gnu_rsync()
    add("rsync", rsync, rsync, "GNU rsync for the disk builder; brew install rsync", "prepare-disk")
    for tool in ("hdiutil", "newfs_hfs", "diskutil", "sudo"):
        found = which(tool, "/sbin", "/usr/sbin")
        add(tool, found, found, "macOS disk tool used by upstream's mkiosroot-mac.sh", "prepare-disk")
    return {"ready": all(item["ok"] for item in checks if item["needed_for"] == "run"),
            "disk_ready": all(item["ok"] for item in checks), "checks": checks,
            "host": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()}}


# --- build: verified kernel and upstream tools --------------------------------

def check_source(source_dir: Path, source: dict, target: dict) -> None:
    verify_source(source_dir, source)
    check = target["source_check"]
    for spec, expected in (("HEAD:xnu/patches", check["patches_tree"]),
                           ("HEAD:.github/workflows/xnu.yml", check["workflow_blob"])):
        actual = git(source_dir, "rev-parse", spec)
        if actual != expected:
            raise NexusError(f"{spec} is {actual}, expected {expected}: the kernel pin no longer matches the source.")


def kernel_cache(work: Path, target: dict) -> Path:
    return work / "downloads" / "ios-qemu-kernel" / target["kernel"]["sha256"] / Path(target["kernel"]["member"]).name


def fetch_kernel(work: Path, target: dict, record: Recorder) -> Path:
    """Download the pinned upstream CI artifact once; publish only a verified kernel."""
    pin = target["kernel"]
    cached = kernel_cache(work, target)
    if cached.is_file() and digest(cached) == pin["sha256"]:
        return cached
    gh = which("gh")
    if not gh:
        raise NexusError("The pinned kernel is not cached and `gh` is missing. Install and `gh auth login`, "
                         "or pass --kernel (docs/ios-qemu.md#kernel).")
    staging = record.directory / "kernel-artifact"
    try:
        record.command([gh, "run", "download", str(pin["run_id"]), "-R", pin["repository"], "-n", pin["artifact"],
                        "-D", str(staging)], cwd=record.directory, timeout=900)
    except NexusError as error:
        raise NexusError(f"{error}. If GitHub expired the artifact (pin says {pin['expires']}), build the kernel "
                         "with upstream's workflow and pass --kernel; see docs/ios-qemu.md#kernel.") from error
    downloaded = staging / relative_path(pin["member"])
    if not downloaded.is_file() or digest(downloaded) != pin["sha256"]:
        raise NexusError(f"Downloaded {pin['member']} does not match the pinned SHA-256.")
    cached.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(downloaded, cached.with_suffix(".partial"))
    cached.with_suffix(".partial").replace(cached)
    shutil.rmtree(staging)  # 150 MB of link archives and dSYM; only the kernel is needed
    return cached


def copy_tools(source_dir: Path, names: tuple[str, ...], destination: Path) -> dict:
    destination.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in names:
        path = source_dir / "tools" / name
        if path.is_symlink() or not path.is_file():
            raise NexusError(f"Expected a regular upstream file: {path}")
        shutil.copyfile(path, destination / name)
        copied[name] = file_record(destination / name)
    return copied


def build_command(ctx) -> dict:
    check_source(ctx.source_dir, ctx.source, ctx.target)
    out = ctx.record.directory
    if ctx.args.kernel:
        kernel_path, origin = ctx.args.kernel.expanduser().resolve(), "user-supplied"
        if not kernel_path.is_file():
            raise NexusError(f"No kernel: {kernel_path}")
    else:
        kernel_path, origin = fetch_kernel(ctx.work, ctx.target, ctx.record), "upstream-ci-artifact"
    shutil.copyfile(kernel_path, out / "kernel")
    if (out / "kernel").read_bytes()[:4] != b"\xcf\xfa\xed\xfe":
        raise NexusError("Kernel is not a 64-bit little-endian Mach-O.")
    tools = copy_tools(ctx.source_dir, BOOT_TOOLS, out / "upstream/tools")
    result = {"schema": 1, "status": "built-not-boot-tested", "target": ctx.target["id"], "source": ctx.source,
              "kernel_origin": origin, "kernel_pin_matches": digest(out / "kernel") == ctx.target["kernel"]["sha256"],
              "kernel_provenance": {key: ctx.target["kernel"][key] for key in ("repository", "run_id", "run_commit")},
              "kernel_source_correspondence": "GitHub-reported CI build of the pinned patch series; not rebuilt here",
              "implementation": implementation_identity(),
              "inputs": {"target_configuration": ctx.target},
              "artifacts": {"kernel": file_record(out / "kernel")}, "tools": tools}
    write_json(out / "build.json", result)
    return result


def read_build(path: Path) -> dict:
    try:
        result = json.loads(path.read_text())
        if (result["schema"] != 1 or set(result["artifacts"]) != {"kernel"} or set(result["tools"]) != set(BOOT_TOOLS)
                or not isinstance(result["inputs"]["target_configuration"], dict)):
            raise ValueError("unsupported build record")
        for item in [*result["artifacts"].values(), *result["tools"].values()]:
            if not isinstance(item["path"], str) or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise ValueError("invalid artifact record")
        return result
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NexusError(f"Cannot read build record {path}: {error}; run ./nexus --target ios-qemu-iphonex build.") from error


def verified(item: dict, label: str) -> Path:
    path = Path(item["path"])
    if not path.is_file() or digest(path) != item["sha256"]:
        raise NexusError(f"{label} changed or is missing: {path}; rebuild or prepare it again.")
    return path


# --- prepare-disk: IPSW -> upstream root-disk builder ---------------------------

def interactive_command(record: Recorder, argv: list[str], cwd: Path, timeout: float) -> None:
    """Like Recorder.command, but in the terminal's session so sudo can prompt.

    Output is mirrored to the terminal and the step log; the password never
    passes through Nexus (sudo reads the terminal itself).
    """
    entry = {"argv": argv, "cwd": str(cwd), "started_unix": time.time(), "interactive": True}
    record.commands.append(entry)
    log = record.directory / f"step-{len(record.commands):02d}.log"
    entry["log"] = log.name
    started = time.monotonic()
    try:
        with log.open("wb") as output, subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE,
                                                       stderr=subprocess.STDOUT) as process:
            for line in iter(process.stdout.readline, b""):
                output.write(line)
                sys.stderr.buffer.write(line)
                sys.stderr.flush()
                if time.monotonic() - started > timeout:
                    process.kill()
                    entry["error"] = "timeout"
                    break
            process.wait()
            entry["returncode"] = process.returncode
    except OSError as error:
        entry["error"] = str(error)
        raise NexusError(f"Cannot run {argv[0]}: {error}") from error
    finally:
        entry["duration_seconds"] = round(time.monotonic() - started, 3)
        write_json(record.directory / "commands.json", record.commands)
    if entry.get("error") or entry["returncode"]:
        raise NexusError(f"{argv[0]} failed ({entry.get('error') or entry['returncode']}). See {log}")


def verify_ipsw(path: Path, target: dict) -> tuple[dict, dict]:
    pin = target["ipsw"]
    if not path.is_file():
        raise NexusError(f"No IPSW at {path}. Download {pin['file']} from Apple yourself (docs/ios-qemu.md#ipsw).")
    data = ipsw.manifest(path)
    types = data.get("SupportedProductTypes", [])
    found = (data.get("ProductVersion"), data.get("ProductBuildVersion"))
    if found != (pin["product_version"], pin["build"]) or pin["product_type"] not in types:
        raise NexusError(f"IPSW is {found} for {types}; this target needs {pin['product_type']} "
                         f"{pin['product_version']} ({pin['build']}).")
    actual = digest(path)
    if actual != pin["sha256"]:
        raise NexusError(f"IPSW SHA-256 {actual} differs from the pin {pin['sha256']}; use Apple's original file.")
    return ({"path": str(path.resolve()), "sha256": actual, "bytes": path.stat().st_size,
             "product_version": found[0], "build": found[1], "product_types": types},
            ipsw.identity(data, pin["board"]))


def device_tree(path: Path, members: dict, destination: Path, target: dict) -> dict:
    staged = ipsw.extract(path, members["DeviceTree"], destination.with_suffix(".im4p"))
    kind, payload = ipsw.im4p_payload(destination.with_suffix(".im4p").read_bytes())
    if kind != "dtre":
        raise NexusError(f"Device tree IM4P has type {kind!r}.")
    destination.write_bytes(payload)
    actual = digest(destination)
    if actual != target["ipsw"]["device_tree_sha256"]:
        raise NexusError(f"Decoded device tree SHA-256 {actual} differs from the pin.")
    return {"im4p": staged, "adt": file_record(destination)}


def prepare_disk_command(ctx) -> tuple[dict, str]:
    """IPSW -> verified members -> upstream mkiosroot-mac.sh (sudo) -> disk.img.

    The upstream script is copied from the pinned checkout; it mounts the
    images read-only and writes only its own new output directory.
    """
    report = doctor(ctx.target)
    if not report["disk_ready"]:
        missing = ", ".join(item["name"] for item in report["checks"] if not item["ok"])
        raise NexusError(f"Host is missing {missing}; run ./nexus --target {ctx.target['id']} doctor.")
    check_source(ctx.source_dir, ctx.source, ctx.target)
    out = ctx.record.directory
    free = shutil.disk_usage(out).free
    if free < 40 * 1024**3:
        raise NexusError(f"Only {free / 1024**3:.0f} GiB free; disk preparation needs about 40 GiB.")
    path = ctx.args.ipsw.expanduser()
    print("Verifying the IPSW (SHA-256 of about 6 GB)...", file=sys.stderr)
    image, members = verify_ipsw(path, ctx.target)
    inputs = out / "inputs"
    extracted = {}
    for key in ("OS", "Cryptex1,SystemOS", "Cryptex1,AppOS"):
        print(f"Extracting {key} ({members[key]})...", file=sys.stderr)
        extracted[key] = ipsw.extract(path, members[key], inputs / Path(members[key]).name)
    tree = device_tree(path, members, out / "d22ap.adt", ctx.target)
    tools = copy_tools(ctx.source_dir, DISK_TOOLS, out / "upstream/tools")
    write_json(out / "inputs.json", {"schema": 1, "ipsw": image, "members": extracted, "device_tree": tree,
                                     "disk_tools": tools, "disk_size": ctx.target["ipsw"]["disk_size"]})
    # Created by this user, not by sudo: the cleanup below must be able to unlink root.hfs.
    disk_dir = out / "disk"
    disk_dir.mkdir()
    print("Building the root disk with upstream's mkiosroot-mac.sh; sudo asks for your password once.",
          file=sys.stderr)
    interactive_command(ctx.record, ["sudo", "/bin/bash", str(out / "upstream/tools/mkiosroot-mac.sh"),
                                     extracted["OS"]["path"], extracted["Cryptex1,SystemOS"]["path"],
                                     extracted["Cryptex1,AppOS"]["path"], str(disk_dir),
                                     ctx.target["ipsw"]["disk_size"]], out, timeout=4 * 3600)
    disk = disk_dir / "disk.img"
    if not disk.is_file():
        raise NexusError("The disk builder finished without disk.img; see the step log.")
    if not ctx.args.keep_inputs:
        shutil.rmtree(inputs)
        (disk_dir / "root.hfs").unlink(missing_ok=True)
    print("Hashing disk.img...", file=sys.stderr)
    result = {"schema": 1, "status": "disk-prepared-not-boot-tested", "target": ctx.target["id"],
              "ipsw": image, "members": extracted, "device_tree": tree, "disk_tools": tools,
              "disk": file_record(disk), "inputs_kept": ctx.args.keep_inputs,
              "implementation": implementation_identity(),
              "note": "Contains Apple software from your IPSW: keep it local; never commit or upload it."}
    write_json(out / "disk.json", result)
    return result, "disk.json"


EXTRA = {"prepare-disk": ("disk", prepare_disk_command)}


def read_disk(path: Path) -> dict:
    """A prepared disk (disk.json) or the disk a previous run left (result.json)."""
    try:
        record = json.loads(path.read_text())
        if record.get("status") == "disk-prepared-not-boot-tested":
            return {"disk": record["disk"], "device_tree": record["device_tree"]["adt"], "origin": str(path)}
        if record.get("scope") == SCOPE and record.get("disk_after"):
            return {"disk": record["disk_after"], "device_tree": record["device_tree"], "origin": str(path)}
        raise ValueError("neither a disk.json nor a run result with a retained disk")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise NexusError(f"Cannot use disk record {path}: {error}. Run prepare-disk first.") from error


# --- evidence ----------------------------------------------------------------

def analyze(text: str) -> dict:
    """Ordered kernel-log milestones. A panic invalidates everything.

    The kernel prints no boot-args, so a log alone cannot prove which run it
    came from: `run` reads it live from that run's guest RAM, and `analyze`
    of a saved file is classification only.
    """
    text = ANSI.sub("", text).replace("\r", "").replace("\0", "")
    panic = PANIC.search(text)
    reached, cursor = [], 0
    for name, pattern in MILESTONES:
        match = re.compile(pattern, re.MULTILINE).search(text, cursor)
        if not match:
            break
        reached.append(name)
        cursor = match.end()
    if len(reached) == len(MILESTONES):
        reached += [name for name, pattern in AFTER_LAUNCHD if re.compile(pattern, re.MULTILINE).search(text, cursor)]
    crashes = Counter(CRASH.findall(text))
    execs = Counter(EXEC.findall(text))
    gui_crash = {name: crashes[name] for name in ("SpringBoard", "backboardd") if crashes[name]}
    restarts = {name: execs[name] - 1 for name in ("SpringBoard", "backboardd") if execs[name] > 1}
    complete = len(reached) == len(ALL_MILESTONES)
    if panic:
        diagnosis = "Kernel panic; inspect kernel.log around the panic and the last exec lines."
    elif not reached:
        diagnosis = "No kernel banner: check launcher.log, qemu/qemu.log and that HVF is usable."
    elif len(reached) < len(MILESTONES):
        diagnosis = f"Reached {reached[-1]}; {MILESTONES[len(reached)][0]} not seen. Read the end of kernel.log."
    elif not complete:
        missing = [name for name, _ in AFTER_LAUNCHD if name not in reached]
        diagnosis = f"launchd started; {', '.join(missing)} not started yet. Read the exec lines in kernel.log."
    elif gui_crash or restarts:
        diagnosis = f"SpringBoard/backboardd crashed or restarted: crashes {gui_crash}, restarts {restarts}."
    else:
        diagnosis = "SpringBoard and backboardd started once without crashing; the GUI checks need a live run."
    return {"milestones": reached, "panic": panic.group(0) if panic else None, "gui_crashes": gui_crash,
            "gui_restarts": restarts, "crash_counts": dict(crashes), "exec_count": sum(execs.values()),
            "exec_counts": {name: execs[name] for name in ("launchd", "SpringBoard", "backboardd", "MobileSafari")
                            if execs[name]},
            "log_complete": complete and not panic and not gui_crash and not restarts, "diagnosis": diagnosis}


def analyze_command(args: argparse.Namespace) -> int:
    if args.log.stat().st_size > MAX_LOG * 4:
        raise NexusError("Log is larger than the 64 MiB analysis limit.")
    result = analyze(args.log.read_text(errors="replace"))
    print(json.dumps(result, indent=2) if args.json else result["diagnosis"])
    return 0 if result["log_complete"] else 1


def screen_stats(raw: bytes) -> dict:
    """Coarse, deterministic content measure over a 64x128 sample grid."""
    if len(raw) != FB_W * FB_H * 4:
        raise NexusError("Unexpected framebuffer size.")
    samples = [raw[(y * FB_H // 128 * FB_W + x * FB_W // 64) * 4:][:3] for y in range(128) for x in range(64)]
    counts = Counter(samples)
    return {"distinct_colours": len(counts), "dominant_fraction": round(counts.most_common(1)[0][1] / len(samples), 4),
            "nonblack_fraction": round(sum(1 for s in samples if max(s) > 16) / len(samples), 4), "samples": samples}


def difference(a: dict, b: dict) -> float:
    changed = sum(1 for x, y in zip(a["samples"], b["samples"])
                  if max(abs(p - q) for p, q in zip(x, y)) > 24)
    return round(changed / len(a["samples"]), 4)


def looks_like_gui(stats: dict) -> bool:
    # A blank/console framebuffer has few colours or one dominant colour.
    return stats["distinct_colours"] >= 64 and stats["dominant_fraction"] < 0.9 and stats["nonblack_fraction"] > 0.2


def write_png(path: Path, raw: bytes) -> None:
    rows = []
    stride = FB_W * 4
    for y in range(FB_H):
        line = raw[y * stride:(y + 1) * stride]
        rgb = bytearray(FB_W * 3)            # a8r8g8b8 little endian = B G R A
        rgb[0::3], rgb[1::3], rgb[2::3] = line[2::4], line[1::4], line[0::4]
        rows.append(b"\0" + bytes(rgb))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", FB_W, FB_H, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"".join(rows), 6)) + chunk(b"IEND", b""))


def screenshot(memory: "GuestMemory", out: Path, name: str) -> dict:
    """Save the guest framebuffer (physical read) as PNG and measure it."""
    raw = memory.read(FB_BASE, FB_W * FB_H * 4)
    write_png(out / (name + ".png"), raw)
    return {"png": file_record(out / (name + ".png")), **screen_stats(raw)}


# --- guest memory without vCPU round-trips --------------------------------------

class GuestMemory:
    """Physical reads through the launcher's QMP socket (connect, read, close).

    QMP `pmemsave` reads guest RAM directly. Virtual reads (`x`, `memsave`,
    `info registers`) make QEMU wait for a vCPU to exit the guest; on the M1
    Pro/macOS 27 host a vCPU never did, which froze QEMU's main loop for good.
    """

    def __init__(self, runtime: Path, timeout: float = 10):
        self.runtime = runtime
        self.timeout = timeout
        self.qmp = None

    def __enter__(self):
        connection = socket.socket(socket.AF_UNIX)
        connection.settimeout(self.timeout)
        try:
            connection.connect(str(self.runtime / "mon.sock"))
        except OSError:
            connection.close()
            raise
        self.qmp = QMP(connection, connection, timeout=self.timeout)
        return self

    def __exit__(self, *_):
        self.qmp.close()

    def read(self, address: int, size: int) -> bytes:
        path = self.runtime / "nexus-read.bin"
        self.qmp.command("pmemsave", {"val": address, "size": size, "filename": str(path)}, timeout=3 * self.timeout)
        data = path.read_bytes()
        path.unlink()
        if len(data) != size:
            raise NexusError("Short guest memory read.")
        return data

    def u64(self, address: int) -> int:
        return struct.unpack("<Q", self.read(address, 8))[0]


class KernelLog:
    """Follow XNU's message buffer by physical address, merging ring snapshots.

    The kernel image is mapped linearly (payload virt_base -> phys_base); a
    buffer that log_setsize() moved to the heap is found by walking the kernel
    page tables (16 KiB granule) from kernel_pmap_store.ttep.
    """
    ANCHOR = 2048

    def __init__(self, kernel: Path, payload: Path):
        from .formats import macho_symbols
        self.symbols = macho_symbols(kernel.read_bytes(), {"_msgbufp", "_kernel_pmap_store"})
        header = payload.read_bytes()[:0x48]
        if header[:8] != b"SWEETXNU":
            raise NexusError("Not a SWEETXNU payload.")
        self.virt_base, _, _, _, self.kernel_end, self.phys_base, _ = struct.unpack_from("<7Q", header, 0x10)
        self.text = bytearray()
        self.gaps = 0

    def physical(self, memory: GuestMemory, va: int) -> int:
        if self.virt_base <= va < self.kernel_end:
            return va - self.virt_base + self.phys_base
        table = memory.u64(self.physical(memory, self.symbols["_kernel_pmap_store"] + 8))  # struct pmap.ttep
        for level, shift in ((1, 36), (2, 25), (3, 14)):
            entry = memory.u64(table + ((va >> shift) & 0x7FF) * 8)
            if not entry & 1:
                raise NexusError(f"Unmapped kernel VA {va:#x} at level {level}.")
            output = entry & 0x0000FFFFFFFFC000
            if level == 3 or not entry & 2:  # page, or block
                return (output & ~((1 << shift) - 1)) | (va & ((1 << shift) - 1))
            table = output
        raise NexusError("Page-table walk did not finish.")

    def snapshot(self, memory: GuestMemory) -> bytes | None:
        pointer = memory.u64(self.physical(memory, self.symbols["_msgbufp"]))
        if not pointer:
            return None
        magic_size, cursor, buffer = struct.unpack("<QQQ", memory.read(self.physical(memory, pointer), 24))
        size, write = magic_size >> 32, cursor & 0xFFFFFFFF
        if (magic_size & 0xFFFFFFFF) != 0x63061 or not 0 < size <= 1 << 22 or write >= size or not buffer:
            return None  # not initialised yet
        data = bytearray()
        offset = 0
        while offset < size:  # page by page: heap buffers are not physically contiguous
            step = min(size - offset, 0x4000 - ((buffer + offset) & 0x3FFF))
            data += memory.read(self.physical(memory, buffer + offset), step)
            offset += step
        return bytes(data[write:] + data[:write]).replace(b"\0", b"")

    def poll(self, memory: GuestMemory) -> bytes:
        """Append what is new since the previous snapshot; return the new bytes."""
        current = self.snapshot(memory)
        if current is None:
            return b""
        new = current
        if self.text:
            # The longest tail of what we have that is still in the ring marks
            # where new output starts; shorter anchors cope with a ring that
            # has just overwritten the oldest part of a long anchor.
            for length in (self.ANCHOR, 256, 48):
                anchor = bytes(self.text[-length:])
                found = current.rfind(anchor)
                if found >= 0:
                    new = current[found + len(anchor):]
                    break
            else:
                self.gaps += 1
                new = b"\n[nexus: kernel log gap: more output than the ring held between reads]\n" + current
        self.text += new
        return new


# --- run ---------------------------------------------------------------------

def guest_processes() -> list[tuple[int, str]]:
    """QEMU guests started by this recipe (any workspace) that are still running."""
    return [(pid, command) for pid, _, command in processes()
            if "qemu-system-aarch64" in command and ("/nexus-" in command or "/.nexus/experiments/" in command)
            and "ufs-lu" in command]


def qemu_child(launcher: int) -> int | None:
    for pid, parent, command in processes():
        if parent == launcher and "qemu-system-aarch64" in command:
            return pid
    return None


def stop_guest(process: subprocess.Popen, qemu_pid: int | None, runtime: Path, steps: list[dict]) -> str:
    """Stop QEMU and its launcher within about 25 s, whatever state they are in.

    1. QMP `quit` on the launcher's socket (QEMU exits; the launcher notices).
    2. If QEMU survives: SIGTERM, then SIGKILL, its exact pid (own process group).
    3. The launcher then exits by itself; otherwise SIGTERM/SIGKILL its group.
    The launcher's own SIGTERM path is avoided first because it runs
    `info registers`, which needs a vCPU round-trip (see GuestMemory).
    """
    def step(name: str, started: float, outcome: str) -> None:
        steps.append({"step": name, "seconds": round(time.monotonic() - started, 2), "outcome": outcome})

    if qemu_pid is None:
        qemu_pid = qemu_child(process.pid)
    if qemu_pid is not None and alive(qemu_pid) and (runtime / "mon.sock").exists():
        started = time.monotonic()
        try:
            connection = socket.socket(socket.AF_UNIX)
            connection.settimeout(3)
            connection.connect(str(runtime / "mon.sock"))
            qmp = QMP(connection, connection, timeout=3)
            try:
                qmp.command("quit", timeout=3)
            except (OSError, NexusError, TimeoutError):
                pass  # QEMU may close the socket before replying
            finally:
                qmp.close()
            step("qmp-quit", started, "exited" if wait_gone(qemu_pid, 5) else "still-running")
        except (OSError, NexusError, TimeoutError) as error:
            step("qmp-quit", started, f"error: {error}")
    if qemu_pid is not None and alive(qemu_pid):
        started = time.monotonic()
        for number, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.kill(qemu_pid, number)
            except ProcessLookupError:
                break
            if wait_gone(qemu_pid, wait):
                break
        step("qemu-signal", started, "gone" if not alive(qemu_pid) else "SURVIVED")
    started = time.monotonic()
    try:
        process.wait(timeout=3)  # it polls QEMU every 0.2 s and exits after it
        step("launcher-exit", started, f"exited {process.returncode}")
    except subprocess.TimeoutExpired:
        for number, wait in ((signal.SIGTERM, 3), (signal.SIGKILL, 3)):
            try:
                os.killpg(process.pid, number)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=wait)
                break
            except subprocess.TimeoutExpired:
                continue
        step("launcher-signal", started, f"exited {process.returncode}" if process.poll() is not None else "survived")
    if qemu_pid is not None and alive(qemu_pid):
        return f"qemu-{qemu_pid}-still-running"
    names = [item["step"] for item in steps]
    return "qmp-quit" if names == ["qmp-quit", "launcher-exit"] and steps[0]["outcome"] == "exited" else "+".join(names)


def short_runtime(directory: Path) -> Path:
    """UNIX socket paths are limited to 104 bytes on macOS; link long paths from /tmp."""
    if len(str(directory / "mon.sock")) <= 100:
        return directory
    link = Path(tempfile.mkdtemp(prefix="nexus-")) / "r"
    link.symlink_to(directory)
    return link


def touch(record: Recorder, tools: Path, runtime: Path, *arguments: str) -> None:
    """Inject input with upstream's qemu-touch.py (QMP input-send-event)."""
    record.command([sys.executable, "-I", str(tools / "qemu-touch.py"), str(runtime), *arguments],
                   cwd=record.directory, timeout=60)


def run_command(ctx, build: dict) -> dict:
    args, target, record = ctx.args, ctx.target, ctx.record
    report = doctor(target)
    if not report["ready"]:
        failures = "; ".join(f"{item['name']}: {item['detail']}" for item in report["checks"]
                             if not item["ok"] and item["needed_for"] == "run")
        raise NexusError("Host is not ready: " + failures)
    stale = guest_processes()
    if stale:
        raise NexusError("Another ios-qemu guest is still running (pid " + ", ".join(str(pid) for pid, _ in stale)
                         + "); two 8 GiB guests do not fit. Stop it (kill PID) and run again.")
    out = record.directory
    disk_path = args.disk
    if disk_path is None:
        from .cli import latest
        disk_path = latest(ctx.work, target["id"], "disk")
        if disk_path is None:
            raise NexusError("No prepared disk; run ./nexus --target ios-qemu-iphonex prepare-disk --ipsw FILE.")
    disk = read_disk(disk_path)
    kernel = verified(build["artifacts"]["kernel"], "Built kernel")
    tools = out / "upstream/tools"
    tools.mkdir(parents=True)
    for name, item in build["tools"].items():
        shutil.copyfile(verified(item, f"Upstream tool {name}"), tools / name)
    adt_input = out / "upstream/research/ipsw-x/d22ap.adt"  # where upstream's mkadt.py looks
    adt_input.parent.mkdir(parents=True)
    shutil.copyfile(verified(disk["device_tree"], "Device tree"), adt_input)
    print("Verifying the source disk image...", file=sys.stderr)
    source_disk = verified(disk["disk"], "Disk image")
    clone = out / "disk.img"
    record.command(["cp", "-c", str(source_disk), str(clone)], cwd=out)  # APFS clone: no data copied
    cpus = target["qemu"]["cpus"]
    bootargs = BOOTARGS.format(cpus=cpus) + (" sweetvsnd=1" if args.audio else "")
    record.command([sys.executable, "-I", str(tools / "mkadt.py"), str(out / "q-ios.adt"), *ADT_ARGS,
                    "--cpus", str(cpus)], cwd=out)
    record.command([sys.executable, "-I", str(tools / "mkpayload.py"), str(kernel), str(out / "q-ios.adt"),
                    str(out / "payload.bin"), "--cmdline", bootargs], cwd=out)
    log_reader = KernelLog(kernel, out / "payload.bin")
    runtime_dir = out / "qemu"
    runtime_dir.mkdir()
    runtime = short_runtime(runtime_dir)
    # No --live-log/--kernel: both read guest *virtual* memory over QMP (see GuestMemory).
    argv = [sys.executable, "-I", str(tools / "qemu-sweet.py"), str(out / "payload.bin"), str(runtime),
            "--secs", "0", "--hvf", "--ufs", str(clone), "--fullfb", "--smp", str(cpus), "--mux-port", "0"] \
        + (["--display"] if args.display else []) + (["--audio"] if args.audio else [])
    write_json(out / "inputs.json", {
        "schema": 1, "target": target, "build": build, "disk_source": disk,
        "bootargs": bootargs, "implementation": implementation_identity(), "host": report,
        "payload": file_record(out / "payload.bin"), "adt": file_record(out / "q-ios.adt"),
        "options": {key: (str(value) if isinstance(value, Path) else value) for key, value in vars(args).items()}})
    write_json(out / "command.json", {"argv": argv, "cwd": str(out)})
    started = time.monotonic()
    status, interrupted = "failed", False
    seen: dict[str, float] = {}
    screens: dict[str, dict] = {}
    interaction: dict = {}
    details = analyze("")
    process = None
    kernel_log = out / "kernel.log"
    errors: list[str] = []
    screen_checks = 0
    qemu_pid = None
    try:
        with kernel_log.open("wb") as log, (out / "launcher.log").open("wb") as launcher:
            process = subprocess.Popen(argv, cwd=out, stdin=subprocess.DEVNULL, stdout=launcher,
                                       stderr=subprocess.STDOUT, start_new_session=True)
            phase, phase_started, last_poll, last_screen = "boot", time.monotonic(), 0.0, 0.0
            failing_since = None
            while True:
                time.sleep(0.5)
                now = time.monotonic()
                elapsed = now - started
                if qemu_pid is None:
                    qemu_pid = qemu_child(process.pid)
                    if qemu_pid is not None:
                        (out / "qemu.pid").write_text(f"{qemu_pid}\n")
                if process.poll() is not None:
                    details["diagnosis"] = f"Launcher exited ({process.returncode}); see launcher.log. " + details["diagnosis"]
                    break
                if elapsed >= args.timeout:
                    status = "timed-out"
                    break
                if now - last_poll < 2 or not (runtime / "mon.sock").exists():
                    continue
                last_poll = now
                try:
                    with GuestMemory(runtime) as memory:
                        log.write(log_reader.poll(memory))
                        log.flush()
                        if phase == "settle" and now - phase_started >= args.settle and now - last_screen >= 10:
                            # First boots show a data-migration progress bar for minutes: poll
                            # until the screen looks like a GUI (or the run times out).
                            last_screen = now
                            screens["springboard"] = screenshot(memory, out, "springboard")
                            screen_checks += 1
                            if not looks_like_gui(screens["springboard"]):
                                details["diagnosis"] = "SpringBoard started; the screen does not look like a GUI yet."
                                continue
                            seen["display"] = round(elapsed, 1)
                            if args.no_interact:
                                status = "passed-display"
                                break
                            phase, phase_started = "unlock", now
                        elif phase == "app-seen" and now - phase_started >= 10:
                            screens["app"] = screenshot(memory, out, "app")
                            interaction["changed_fraction"] = difference(screens["springboard"], screens["app"])
                            if interaction["changed_fraction"] >= 0.05:
                                seen["interaction"] = round(elapsed, 1)
                                status = "passed"
                            else:
                                details["diagnosis"] = "Safari started after the tap, but the screen did not change."
                            break
                        elif phase == "unlocked" and now - phase_started >= 5:
                            screens["unlocked"] = screenshot(memory, out, "unlocked")
                            interaction = {"log_offset": len(log_reader.text), "tap": SAFARI, "app": "MobileSafari",
                                           "seen_before_tap": bool(re.search(LINE.encode() + rb"exec MobileSafari$", log_reader.text,
                                                                             re.MULTILINE))}
                            phase = "tap"
                except (OSError, NexusError, TimeoutError) as error:
                    # A busy QEMU can miss a read; 30 s without any answer means its main
                    # loop is wedged (reproduced: a QMP virtual-memory read that waits for
                    # a vCPU forever). Stop instead of waiting for the overall timeout.
                    errors.append(f"{round(elapsed, 1)}s: {error}")
                    failing_since = failing_since or now
                    if now - failing_since >= UNRESPONSIVE:
                        details["diagnosis"] = (f"QEMU stopped answering QMP for {UNRESPONSIVE} s (main loop "
                                                "wedged); see result.json monitor_errors and docs/ios-qemu.md.")
                        status = "failed"
                        break
                    continue
                failing_since = None
                details = analyze(log_reader.text.decode(errors="replace"))
                for name in details["milestones"]:
                    seen.setdefault(name, round(elapsed, 1))
                if details["panic"] or details["gui_crashes"] or details["gui_restarts"]:
                    break
                if phase == "boot" and "springboard" in details["milestones"]:
                    phase, phase_started = "settle", now
                elif phase == "unlock":
                    touch(record, tools, runtime, "unlock")
                    phase, phase_started = "unlocked", time.monotonic()
                elif phase == "tap":
                    touch(record, tools, runtime, "tap", *map(str, SAFARI))
                    phase, phase_started = "interact", time.monotonic()
                elif phase == "interact":
                    after = bytes(log_reader.text[interaction["log_offset"]:])
                    if re.search(LINE.encode() + rb"exec MobileSafari$", after, re.MULTILINE):
                        interaction["exec_after_tap"] = True
                        phase, phase_started = "app-seen", now
                    elif now - phase_started > 90:
                        interaction["exec_after_tap"] = False
                        details["diagnosis"] = "No Safari process within 90 s of the injected tap."
                        break
            if args.hold and status.startswith("passed"):
                print(f"Checks done; holding the guest for {args.hold:.0f} s.", file=sys.stderr)
                time.sleep(args.hold)
    except KeyboardInterrupt:
        status, interrupted = "interrupted", True
    except (OSError, NexusError, TimeoutError) as error:
        details["diagnosis"] = f"Cannot operate the run: {error}"
        status = "failed"
    finally:
        # Bounded cleanup (about 45 s worst case); repeated Ctrl-C cannot abort it half-way.
        with deferred_signals() as late:
            shutdown, shutdown_steps = "not-started", []
            if process:
                if process.poll() is None and qemu_pid is not None and not interrupted:
                    try:  # final screen for diagnosis; skipped when the user asked to stop
                        with GuestMemory(runtime, timeout=5) as memory:
                            screens.setdefault("final", screenshot(memory, out, "final"))
                    except (OSError, NexusError, TimeoutError) as error:
                        errors.append(f"final screen: {error}")
                print("Stopping QEMU (bounded, at most about 40 s)...", file=sys.stderr)
                shutdown = stop_guest(process, qemu_pid, runtime, shutdown_steps)
            if runtime != runtime_dir:
                runtime.unlink()
                runtime.parent.rmdir()
            final = analyze(log_reader.text.decode(errors="replace"))
            if final["panic"] or final["gui_crashes"] or final["gui_restarts"]:
                status = status if interrupted else "failed"
                details = final
            elif not status.startswith("passed"):
                details = {**final, "diagnosis": details["diagnosis"]}
            else:
                details = final
            if shutdown.startswith("qemu-") and shutdown.endswith("-still-running"):
                status = "failed" if not interrupted else status
                details["diagnosis"] = f"QEMU could not be stopped ({shutdown}); kill it before another run."
            if status == "passed":
                details["diagnosis"] = ("Stock iOS 16.7.16 userland reached SpringBoard, drew a GUI and launched "
                                        "Safari from injected touch input. Not a supported or secure iOS device.")
            elif status == "passed-display":
                details["diagnosis"] = "SpringBoard drew a GUI; interaction was skipped (--no-interact)."
            result = {"schema": 1, "status": status, "target": target["id"], "scope": SCOPE,
                      "log_source": "physical reads of this run's live guest RAM",
                      "milestones": details["milestones"] + [n for n in GUI if n in seen],
                      "milestone_seconds": seen, "evidence": details,
                      "screens": {k: {x: y for x, y in v.items() if x != "samples"} for k, v in screens.items()},
                      "interaction": interaction, "shutdown": shutdown, "shutdown_steps": shutdown_steps,
                      "qemu_pid": qemu_pid, "signals_during_cleanup": late[:], "monitor_errors": errors[-30:],
                      "screen_checks": screen_checks, "log_gaps": log_reader.gaps,
                      "duration_seconds": round(time.monotonic() - started, 3),
                      "kernel_log": file_record(kernel_log) if kernel_log.exists() else None,
                      "disk_source": disk, "disk_after": None, "device_tree": disk["device_tree"],
                      "implementation": implementation_identity(), "build_record": build}
            write_json(out / "result.json", result)
            interrupted = interrupted or bool(late)
    # Optional and interruptible: lets `run --disk <this result.json>` continue from this disk.
    if clone.exists() and process is not None and not interrupted:
        print("Hashing the run's disk clone for --disk reuse (about 10 s; Ctrl-C skips)...", file=sys.stderr)
        try:
            result["disk_after"] = file_record(clone)
        except KeyboardInterrupt:
            interrupted = True
        write_json(out / "result.json", result)
    if interrupted:
        raise KeyboardInterrupt
    return result
