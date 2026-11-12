"""Process lifecycle without a guest: fake launchers and fake QEMU processes."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

from nexuslib.iosqemu import qemu_child, stop_guest
from nexuslib.qemu import alive, deferred_signals, signals_as_interrupt

# A stand-in for upstream's qemu-sweet.py: starts a child whose argv[0] is
# qemu-system-aarch64 in its own process group (like process_group=0), then
# waits for it. Either may ignore SIGTERM to model a wedged process.
LAUNCHER = textwrap.dedent("""
    import os, signal, subprocess, sys, time
    mode, runtime = sys.argv[1], sys.argv[2]
    if "launcher-ignores-term" in mode:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    # The trailing marker makes `ps` show "qemu-system-aarch64" like the real child.
    child = subprocess.Popen([sys.executable, "-c", sys.argv[3], mode, runtime, "qemu-system-aarch64"],
                             process_group=0)
    open(os.path.join(runtime, "child.pid"), "w").write(str(child.pid))
    while child.poll() is None:
        time.sleep(0.05)
""")
# Fake QEMU: optional QMP server on mon.sock that exits on "quit".
FAKE_QEMU = textwrap.dedent("""
    import json, os, signal, socket, sys, time
    mode, runtime = sys.argv[1], sys.argv[2]
    if "qemu-ignores-term" in mode:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if "qmp" not in mode:
        while True:
            time.sleep(1)
    server = socket.socket(socket.AF_UNIX)
    server.bind(os.path.join(runtime, "mon.sock"))
    server.listen(1)
    while True:
        connection, _ = server.accept()
        stream = connection.makefile("rw")
        stream.write(json.dumps({"QMP": {"version": {}}}) + "\\n"); stream.flush()
        for line in stream:
            request = json.loads(line)
            stream.write(json.dumps({"return": {}, "id": request.get("id")}) + "\\n"); stream.flush()
            if request["execute"] == "quit":
                os._exit(0)
""")


class FakeGuest:
    def __init__(self, mode: str):
        self.tmp = tempfile.TemporaryDirectory(prefix="nx")
        self.runtime = Path(self.tmp.name)
        self.launcher = subprocess.Popen([sys.executable, "-c", LAUNCHER, mode, str(self.runtime), FAKE_QEMU],
                                         start_new_session=True)
        deadline = time.monotonic() + 10
        while not (self.runtime / "child.pid").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.qemu = int((self.runtime / "child.pid").read_text())
        if "qmp" in mode:
            while not (self.runtime / "mon.sock").exists() and time.monotonic() < deadline:
                time.sleep(0.05)

    def close(self):
        for pid in (self.qemu, self.launcher.pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self.launcher.wait()
        self.tmp.cleanup()


class StopGuestTests(unittest.TestCase):
    def stop(self, mode: str) -> tuple[str, list, float, FakeGuest]:
        guest = FakeGuest(mode)
        self.addCleanup(guest.close)
        steps: list = []
        started = time.monotonic()
        outcome = stop_guest(guest.launcher, guest.qemu, guest.runtime, steps)
        return outcome, steps, time.monotonic() - started, guest

    def test_qmp_quit_is_the_fast_path(self):
        outcome, steps, seconds, guest = self.stop("qmp")
        self.assertEqual(outcome, "qmp-quit", steps)
        self.assertFalse(alive(guest.qemu))
        self.assertIsNotNone(guest.launcher.poll())
        self.assertLess(seconds, 5)

    def test_without_qmp_signals_escalate(self):
        outcome, steps, seconds, guest = self.stop("plain")
        self.assertFalse(alive(guest.qemu))
        self.assertIsNotNone(guest.launcher.poll())
        self.assertNotIn("still-running", outcome)
        self.assertLess(seconds, 20)

    def test_everything_ignores_sigterm_still_bounded(self):
        outcome, steps, seconds, guest = self.stop("launcher-ignores-term,qemu-ignores-term")
        self.assertFalse(alive(guest.qemu), steps)
        self.assertIsNotNone(guest.launcher.poll())
        self.assertIn("qemu-signal", [step["step"] for step in steps])
        self.assertLess(seconds, 25)

    def test_unknown_pid_is_found_from_the_launcher(self):
        guest = FakeGuest("plain")
        self.addCleanup(guest.close)
        self.assertEqual(qemu_child(guest.launcher.pid), guest.qemu)
        stop_guest(guest.launcher, None, guest.runtime, [])
        self.assertFalse(alive(guest.qemu))


class SignalTests(unittest.TestCase):
    def test_sigterm_and_sighup_become_interrupts(self):
        for number in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=number), self.assertRaises(KeyboardInterrupt), signals_as_interrupt():
                os.kill(os.getpid(), number)
                time.sleep(1)
        # Handlers are restored afterwards.
        self.assertIsNot(signal.getsignal(signal.SIGTERM), None)

    def test_cleanup_is_not_aborted_by_repeated_signals(self):
        finished = False
        with deferred_signals() as late:
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGTERM)
            time.sleep(0.2)
            finished = True
        self.assertTrue(finished)
        self.assertEqual(sorted(late), sorted([signal.SIGINT, signal.SIGTERM]))
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)


if __name__ == "__main__":
    unittest.main()
