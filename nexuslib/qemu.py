"""Bounded QEMU experiments, QMP diagnostics and conservative boot evidence."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import select
import subprocess
import time

from .core import NexusError, Recorder, digest, implementation_identity, write_json
from .formats import payload_pack
from .host import doctor, file_record


CHECKS = ("console", "pid1", "uid0", "sysctl", "boot-token", "errno", "mmap-rw", "mprotect", "munmap", "timer")
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[()][A-Za-z0-9]|\x1b=[0-9]*[a-z]?")
PANIC = re.compile(r"panic\(cpu |^panic:|Kernel panic|^NEXUS (?:CHECK \S+|RESULT) FAIL", re.MULTILINE)
STAGES = (
    ("loader", r"^== XNULOADER v3 ==$"),
    ("kernel", r"^Darwin Kernel Version [0-9].*$"),
    ("root", r"^BSD root: md0,.*$"),
    ("userspace", r"^NEXUS PROBE 1$"),
)
MAX_LOG = 16 * 1024 * 1024


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


class QMP:
    """Synchronous, bounded QMP with message IDs and asynchronous event handling."""

    def __init__(self, reader, writer, timeout: float = 2):
        self.reader, self.writer = reader, writer
        self.buffer = bytearray()
        self.counter = 0
        try:
            greeting = self._read(time.monotonic() + timeout)
            if "QMP" not in greeting:
                raise NexusError("Invalid QMP greeting.")
            self.command("qmp_capabilities", timeout=timeout)
        except Exception:
            self.close()
            raise

    def _read(self, deadline: float) -> dict:
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([self.reader], [], [], remaining)[0]:
                raise TimeoutError("QMP response deadline exceeded")
            chunk = os.read(self.reader.fileno(), 65536)
            if not chunk:
                raise NexusError("QMP connection closed.")
            self.buffer += chunk
            if len(self.buffer) > 1024 * 1024:
                raise NexusError("QMP response exceeds 1 MiB.")
        line, _, remaining = self.buffer.partition(b"\n")
        self.buffer = bytearray(remaining)
        try:
            result = json.loads(line)
            if not isinstance(result, dict):
                raise ValueError("QMP message must be an object")
            return result
        except (ValueError, UnicodeDecodeError) as error:
            raise NexusError("Malformed QMP response.") from error

    def command(self, name: str, arguments: dict | None = None, timeout: float = 2):
        self.counter += 1
        request = {"execute": name, "id": self.counter}
        if arguments:
            request["arguments"] = arguments
        data = memoryview(json.dumps(request).encode() + b"\n")
        while data:
            count = os.write(self.writer.fileno(), data)
            data = data[count:]
        deadline = time.monotonic() + timeout
        while True:
            reply = self._read(deadline)
            if reply.get("id") != self.counter:
                continue
            if "error" in reply:
                raise NexusError(f"QMP {name}: {reply['error']}")
            if "return" not in reply:
                raise NexusError(f"QMP {name}: missing result")
            return reply["return"]

    def close(self):
        self.reader.close()
        self.writer.close()


def qemu_path(path: Path) -> str:
    # QEMU's key=value option grammar uses doubled commas for literal commas.
    return str(path).replace(",", ",,")


def stop(process: subprocess.Popen, qmp: QMP | None) -> str:
    if process.poll() is not None:
        return "already-exited"
    if qmp:
        try:
            qmp.command("quit")
            process.wait(timeout=3)
            return "qmp-quit"
        except (OSError, NexusError, TimeoutError, subprocess.TimeoutExpired):
            pass
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=3)
        return "terminated"
    except ProcessLookupError:
        process.wait(timeout=3)
        return "already-exited"
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=3)
        return "killed"


def run(target: dict, build: dict, record: Recorder, *, timeout: float = 90,
        code: str | None = None, variables: str | None = None, gdb_port: int | None = None) -> dict:
    environment = doctor(code, variables, loader=build["loader_mode"], runtime_only=True,
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
                  "qemu_returncode": process.returncode if process else None,
                  "evidence": details, "serial": file_record(serial) if serial.exists() else None,
                  "build_record": build, "scope": "open-xnu-userspace-probe"}
        write_json(out / "result.json", result)
    if interruption:
        raise KeyboardInterrupt
    return result
