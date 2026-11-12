"""Shared QEMU process mechanics: bounded QMP, shutdown and log limits.

Boot contracts (payload layout, stages, acceptance checks) belong to recipes.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import time

from .core import NexusError

MAX_LOG = 16 * 1024 * 1024


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


# --- process lifecycle shared by recipes ---------------------------------------

STOP_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


@contextmanager
def signals_as_interrupt():
    """Treat SIGTERM/SIGHUP like Ctrl-C so `finally` blocks stop QEMU.

    Guests run in their own session (a terminal's Ctrl-C must not reach QEMU
    before Nexus has saved evidence), so without this a `kill` of Nexus or a
    closed terminal would orphan a running guest.
    """
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    previous = {}
    for number in (signal.SIGTERM, signal.SIGHUP):
        try:
            previous[number] = signal.signal(number, interrupt)
        except ValueError:  # not the main thread (tests)
            pass
    try:
        yield
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


@contextmanager
def deferred_signals():
    """Run a *bounded* cleanup without a second Ctrl-C aborting it half-way.

    Yields a list that records any stop signals received meanwhile; the caller
    decides whether to report an interruption afterwards.
    """
    received: list[int] = []
    previous = {}
    for number in STOP_SIGNALS:
        try:
            previous[number] = signal.signal(number, lambda signum, frame: received.append(signum))
        except ValueError:
            pass
    try:
        yield received
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_gone(pid: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def processes() -> list[tuple[int, int, str]]:
    """(pid, parent pid, command line) of this user's processes; empty if ps fails."""
    try:
        listing = subprocess.run(["ps", "-x", "-o", "pid=,ppid=,command="], capture_output=True,
                                 text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows = []
    for line in listing.splitlines():
        fields = line.split(None, 2)
        if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
            rows.append((int(fields[0]), int(fields[1]), fields[2]))
    return rows
