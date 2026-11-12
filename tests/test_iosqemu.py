import io
import json
from pathlib import Path
import platform
import tempfile
import unittest
from unittest import mock
import zipfile
import plistlib
import re
import struct

from nexuslib import cli, ipsw
from nexuslib.cli import ROOT, recipe_for
from nexuslib.core import NexusError, load_target
from nexuslib.iosqemu import (FB_H, FB_W, KernelLog, analyze, difference, looks_like_gui, read_build,
                              read_disk, screen_stats)

TARGET = ROOT / "targets/ios-qemu-iphonex/target.toml"


def der(tag: int, content: bytes) -> bytes:
    if len(content) < 0x80:
        return bytes([tag, len(content)]) + content
    size = len(content).to_bytes((len(content).bit_length() + 7) // 8, "big")
    return bytes([tag, 0x80 | len(size)]) + size + content


def im4p(kind: bytes, payload: bytes, *extra: bytes) -> bytes:
    return der(0x30, der(0x16, b"IM4P") + der(0x16, kind) + der(0x16, b"test") + der(0x04, payload) + b"".join(extra))


def boot_log(*extra: str) -> str:
    return "\n".join([
        "[    0.006449]: Darwin Kernel Version 22.6.0: test",
        "[    0.049614]: BSD root: ufsroot0, major 1, minor 0",
        "[    0.153071]: exec launchd",
        "[    0.979067]: exec SpringBoard",   # observed order: SpringBoard before backboardd
        "[    1.170380]: exec backboardd",
        *extra, ""])


class IPSWTests(unittest.TestCase):
    def test_plain_payload(self):
        self.assertEqual(ipsw.im4p_payload(im4p(b"dtre", b"tree" * 100)), ("dtre", b"tree" * 100))

    def test_rejects_encrypted_unknown_and_truncated(self):
        with self.assertRaisesRegex(NexusError, "encrypted"):
            ipsw.im4p_payload(im4p(b"dtre", b"data", der(0x04, b"keybag")))
        with self.assertRaises(NexusError):
            ipsw.im4p_payload(im4p(b"dtre", b"complzss" + b"x" * 8))
        with self.assertRaises(NexusError):
            ipsw.im4p_payload(der(0x30, der(0x16, b"IMG4") + der(0x16, b"dtre")))
        whole = im4p(b"dtre", b"x" * 300)
        for cut in (1, 3, len(whole) // 2, len(whole) - 1):
            with self.subTest(cut=cut), self.assertRaises(NexusError):
                ipsw.im4p_payload(whole[:cut])

    @unittest.skipUnless(platform.system() == "Darwin", "LZFSE uses macOS libcompression")
    def test_lzfse_size_must_match(self):
        record = der(0x30, der(0x02, b"\x01") + der(0x02, b"\x10"))
        with self.assertRaises(NexusError):
            ipsw.im4p_payload(im4p(b"dtre", b"bvx2garbage", record))

    def test_manifest_identity_and_member_safety(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.ipsw"
            manifest = {"ProductVersion": "16.7.16", "BuildIdentities": [
                {"Info": {"DeviceClass": "d22ap", "RestoreBehavior": "Erase"},
                 "Manifest": {"OS": {"Info": {"Path": "os.dmg"}}, "DeviceTree": {"Info": {"Path": "dt.im4p"}}}}]}
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr("BuildManifest.plist", plistlib.dumps(manifest))
                archive.writestr("os.dmg", b"disk")
            data = ipsw.manifest(path)
            self.assertEqual(ipsw.identity(data, "d22ap"), {"OS": "os.dmg", "DeviceTree": "dt.im4p"})
            with self.assertRaises(NexusError):
                ipsw.identity(data, "d221ap")
            record = ipsw.extract(path, "os.dmg", Path(tmp) / "out/os.dmg")
            self.assertEqual(record["bytes"], 4)
            for name in ("../escape", "/abs", "a\\b", ""):
                with self.subTest(name=name), self.assertRaises(NexusError):
                    ipsw.extract(path, name, Path(tmp) / "x")
            with self.assertRaisesRegex(NexusError, "missing"):
                ipsw.extract(path, "dt.im4p", Path(tmp) / "dt")


class MilestoneTests(unittest.TestCase):
    def test_complete_log(self):
        result = analyze(boot_log())
        self.assertEqual(result["milestones"], ["kernel", "root", "launchd", "backboardd", "springboard"])
        self.assertTrue(result["log_complete"])

    def test_unprefixed_lines_also_count(self):
        self.assertTrue(analyze(re.sub(r"\[\s*[0-9.]+\]: ", "", boot_log()))["log_complete"])

    def test_chain_order_required(self):
        lines = boot_log().splitlines()
        lines.remove("[    0.153071]: exec launchd")
        lines.insert(0, "[    0.000001]: exec launchd")
        result = analyze("\n".join(lines))
        self.assertEqual(result["milestones"], ["kernel", "root"])
        self.assertFalse(result["log_complete"])

    def test_gui_processes_must_follow_launchd(self):
        text = "[ 0.1]: exec SpringBoard\n[ 0.1]: exec backboardd\n" + boot_log().replace(
            "[    0.979067]: exec SpringBoard\n", "").replace("[    1.170380]: exec backboardd\n", "")
        self.assertEqual(analyze(text)["milestones"], ["kernel", "root", "launchd"])

    def test_exec_must_be_exact_line(self):
        text = boot_log().replace("exec SpringBoard", "exec SpringBoardHelper")
        self.assertNotIn("springboard", analyze(text)["milestones"])

    def test_panic_crash_and_restart_reject(self):
        self.assertFalse(analyze(boot_log("[    9.0]: panic(cpu 0 caller 0x0): test"))["log_complete"])
        self.assertFalse(analyze(boot_log("panic_trace: PE_arm_debug_enable_trace enter"))["panic"])
        crashed = analyze(boot_log("[    5.0]: CRASH SpringBoard[52] sig 11 code 0"))
        self.assertEqual(crashed["gui_crashes"], {"SpringBoard": 1})
        self.assertFalse(crashed["log_complete"])
        restarted = analyze(boot_log("[    6.0]: exec SpringBoard"))
        self.assertEqual(restarted["gui_restarts"], {"SpringBoard": 1})
        other = analyze(boot_log("[    4.057916]: CRASH driverkitd[66] sig 9 code 0x0 sub 0x0"))
        self.assertTrue(other["log_complete"])
        self.assertEqual(other["crash_counts"], {"driverkitd": 1})

    def test_nul_ansi_and_crlf(self):
        text = "\0\x1b[1m" + boot_log().replace("\n", "\r\n")
        self.assertTrue(analyze(text)["log_complete"])


class ScreenTests(unittest.TestCase):
    def test_blank_and_console_are_not_gui(self):
        black = bytes(FB_W * FB_H * 4)
        self.assertFalse(looks_like_gui(screen_stats(black)))
        console = bytearray(black)
        console[: FB_W * 4 * 40] = b"\xff\xff\xff\x00" * (FB_W * 40)
        self.assertFalse(looks_like_gui(screen_stats(bytes(console))))

    def test_gradient_is_gui_and_difference(self):
        line = lambda y: b"".join(bytes([(x * 255 // FB_W), (y * 255 // FB_H), ((x + y) % 256), 255]) for x in range(FB_W))
        raw = b"".join(line(y) for y in range(FB_H))
        stats = screen_stats(raw)
        self.assertTrue(looks_like_gui(stats))
        self.assertEqual(difference(stats, stats), 0)
        self.assertGreater(difference(stats, screen_stats(bytes(len(raw)))), 0.5)

    def test_wrong_size(self):
        with self.assertRaises(NexusError):
            screen_stats(b"\0" * 16)


class TargetTests(unittest.TestCase):
    def test_target_loads_and_rejects_untested_settings(self):
        target = load_target(TARGET)
        recipe_for(target)
        for section, field, value in (("qemu", "accel", "tcg"), ("qemu", "cpus", 0), ("qemu", "cpus", True),
                                      ("qemu", "extra", 1), ("kernel", "sha256", "abc"),
                                      ("kernel", "member", "../x"), ("ipsw", "disk_size", "16"),
                                      ("source_check", "patches_tree", "main")):
            changed = {**target, section: {**target[section], field: value}}
            with self.subTest(field=field, value=value), self.assertRaises(NexusError):
                recipe_for(changed)
        with self.assertRaises(NexusError):
            recipe_for({**target, "loader": {}})

    def test_records_are_validated(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "record.json"
            for content in ("not-json", "{}", '{"schema": 1, "artifacts": {}}'):
                path.write_text(content)
                with self.subTest(content=content), self.assertRaises(NexusError):
                    read_build(path)
                with self.subTest(content=content), self.assertRaises(NexusError):
                    read_disk(path)

    def test_cli_commands_follow_the_target(self):
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit):
            cli.main(["--target", "ios-qemu-iphonex", "--help"])
        self.assertIn("prepare-disk", out.getvalue())
        self.assertNotIn("prepare-kernel", out.getvalue())
        out = io.StringIO()
        with mock.patch("sys.stdout", out), self.assertRaises(SystemExit):
            cli.main(["--help"])
        self.assertIn("prepare-kernel", out.getvalue())
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            cli.main(["--target", "qemu-virt-xnu", "prepare-disk", "--ipsw", "x"])

    def test_analyze_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "kernel.log"
            log.write_text(boot_log())
            with mock.patch("sys.stdout", io.StringIO()) as out:
                self.assertEqual(cli.main(["--target", "ios-qemu-iphonex", "analyze", str(log), "--json"]), 0)
            self.assertTrue(json.loads(out.getvalue())["log_complete"])
            log.write_text(boot_log().replace("exec SpringBoard", "exec Other"))
            with mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(cli.main(["--target", "ios-qemu-iphonex", "analyze", str(log)]), 1)


if __name__ == "__main__":
    unittest.main()


class FakeMemory:
    def __init__(self):
        self.pages = {}

    def write(self, address, data):
        for index, byte in enumerate(data):
            self.pages[address + index] = byte

    def read(self, address, size):
        return bytes(self.pages.get(address + index, 0) for index in range(size))

    def u64(self, address):
        return struct.unpack("<Q", self.read(address, 8))[0]


class KernelLogTests(unittest.TestCase):
    VIRT, PHYS, END = 0xFFFFFE0006000000, 0x100000000, 0xFFFFFE0008000000
    MSGBUFP, PMAP, MSGBUF = 0xFFFFFE0007B82738, 0xFFFFFE0007BE9730, 0xFFFFFE0007B82720

    def reader(self):
        log = KernelLog.__new__(KernelLog)
        log.symbols = {"_msgbufp": self.MSGBUFP, "_kernel_pmap_store": self.PMAP}
        log.virt_base, log.kernel_end, log.phys_base = self.VIRT, self.END, self.PHYS
        log.text, log.gaps = bytearray(), 0
        return log

    def linear(self, va):
        return va - self.VIRT + self.PHYS

    def ring(self, memory, header_va, buffer_va, buffer_pa, size, content: bytes, write: int):
        memory.write(self.linear(self.MSGBUFP), struct.pack("<Q", header_va))
        memory.write(self.linear(header_va), struct.pack("<IIIIQ", 0x63061, size, write, 0, buffer_va))
        memory.write(buffer_pa, content.ljust(size, b"\0"))

    def test_linear_ring_wraps_and_merges(self):
        memory, log = FakeMemory(), self.reader()
        buffer_va, size = 0xFFFFFE0007C05D2C, 128
        first = b"".join(b"line %02d of early kernel output\n" % i for i in range(3)) + b"exec launchd\n"
        self.ring(memory, self.MSGBUF, buffer_va, self.linear(buffer_va), size, first, len(first))
        self.assertEqual(log.poll(memory), first)
        self.assertEqual(log.poll(memory), b"")
        # The ring wraps and overwrites the oldest part of the previous output; the
        # 2 KiB and 256-byte anchors are gone, the 48-byte one still matches.
        stream = first + b"exec backboardd\nexec SpringBoard\nmore output after it\n"
        ring = bytearray(size)
        for index in range(len(stream) - size, len(stream)):
            ring[index % size] = stream[index]
        memory.write(self.linear(buffer_va), bytes(ring))
        memory.write(self.linear(self.MSGBUF) + 8, struct.pack("<I", len(stream) % size))
        log.poll(memory)
        self.assertEqual(bytes(log.text), stream)
        self.assertEqual(log.gaps, 0)
        self.assertEqual(analyze(stream.decode())["exec_counts"]["SpringBoard"], 1)

    def test_heap_buffer_page_walk_and_gap(self):
        memory, log = FakeMemory(), self.reader()
        root, level2, level3 = 0x200000000, 0x200004000, 0x200008000
        memory.write(self.linear(self.PMAP) + 8, struct.pack("<Q", root))
        heap_va, heap_pa = 0xFFFFFE1000004010, 0x300000010
        memory.write(root + ((heap_va >> 36) & 0x7FF) * 8, struct.pack("<Q", level2 | 3))
        memory.write(level2 + ((heap_va >> 25) & 0x7FF) * 8, struct.pack("<Q", level3 | 3))
        memory.write(level3 + ((heap_va >> 14) & 0x7FF) * 8, struct.pack("<Q", (heap_pa & ~0x3FFF) | 3))
        self.assertEqual(log.physical(memory, heap_va), heap_pa)
        with self.assertRaises(NexusError):
            log.physical(memory, heap_va + (1 << 36))
        self.ring(memory, self.MSGBUF, heap_va, heap_pa, 32, b"abc\n", 4)
        self.assertEqual(log.poll(memory), b"abc\n")
        self.ring(memory, self.MSGBUF, heap_va, heap_pa, 32, b"entirely different output\n", 26)
        log.poll(memory)
        self.assertEqual(log.gaps, 1)
        self.assertIn(b"kernel log gap", bytes(log.text))

    def test_uninitialised_buffer_is_ignored(self):
        memory, log = FakeMemory(), self.reader()
        self.assertEqual(log.poll(memory), b"")
        memory.write(self.linear(self.MSGBUFP), struct.pack("<Q", self.MSGBUF))
        self.assertEqual(log.poll(memory), b"")  # wrong magic
