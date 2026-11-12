import struct
import unittest

from nexuslib.core import NexusError
from nexuslib.formats import macho_info, payload_pack, payload_unpack, static_entry


def linked_fixture():
    """Synthetic format fixture, not executable guest evidence."""
    segment = bytearray(struct.pack("<II16s4Q4I", 0x19, 152, b"__TEXT", 0x100000000,
                                    0x4000, 0, 0x4000, 7, 5, 1, 0))
    section = bytearray(80)
    section[:6] = b"__text"
    struct.pack_into("<I", section, 48, 0x1000)
    segment += section
    main = struct.pack("<IIQQ", 0x80000028, 24, 0x1000, 0)
    linker = struct.pack("<II", 0xE, 16) + bytes(8)
    commands = segment + main + linker
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 3, len(commands), 0x200085, 0)
    return (header + commands).ljust(0x4000, b"\0")


class PayloadTests(unittest.TestCase):
    def test_exact_wire_layout_and_alignment(self):
        data = payload_pack({"kernel": b"abc", "ramdisk": b"x" * 17})
        self.assertEqual(data[:8], struct.pack("<II", 0x50554E58, len(data) - 8))
        self.assertEqual(struct.unpack_from("<16sII", data, 8), (b"kernel" + bytes(10), 3, 0))
        self.assertEqual(data[32:48], b"abc" + bytes(13))
        self.assertEqual(data[48:64], b"ramdisk" + bytes(9))
        self.assertEqual(payload_unpack(data), {"kernel": b"abc", "ramdisk": b"x" * 17})

    def test_all_padding_lengths(self):
        for size in range(34):
            with self.subTest(size=size):
                items = {"kernel": bytes(range(size)), "cmdline": b"a\0"}
                self.assertEqual(payload_unpack(payload_pack(items)), items)

    def test_every_truncation_rejected(self):
        good = payload_pack({"kernel": b"abcd"})
        for end in range(len(good)):
            with self.subTest(end=end):
                with self.assertRaises(NexusError):
                    payload_unpack(good[:end])

    def test_invalid_names(self):
        for name in ("", "x" * 16, "bad\0name", "日本語"):
            with self.subTest(name=name), self.assertRaises(NexusError):
                payload_pack({name: b"x"})

    def test_duplicate_header_padding_and_trailing_data(self):
        data = bytearray(payload_pack({"kernel": b"a", "ramdisk": b"b"}))
        for offset, value in ((0, 0), (4, 0), (28, 1), (33, 1), (48, ord("k"))):
            broken = data.copy()
            broken[offset] = value
            if offset == 48:
                broken[48:64] = broken[8:24]
            with self.subTest(offset=offset), self.assertRaises(NexusError):
                payload_unpack(broken)

    def test_wrong_length_with_valid_magic(self):
        data = payload_pack({"kernel": b"x"}) + b"garbage"
        with self.assertRaises(NexusError):
            payload_unpack(data)


class MachoTests(unittest.TestCase):
    def test_static_entry_pc_and_flags(self):
        data = static_entry(linked_fixture())
        info = macho_info(data)
        self.assertEqual(info["flags"], 1)
        count, size = struct.unpack_from("<II", data, 16)
        self.assertEqual(count, 2)
        thread = data[32 + size - 288:32 + size]
        self.assertEqual(struct.unpack_from("<4I", thread), (5, 288, 6, 68))
        self.assertEqual(struct.unpack_from("<Q", thread, 16 + 256)[0], 0x100001000)
        self.assertEqual(data[0x1000:], linked_fixture()[0x1000:])

    def test_dynamic_executable_rejected_by_inspector(self):
        with self.assertRaises(NexusError):
            macho_info(linked_fixture())

    def test_malformed_headers(self):
        for data in (b"", bytes(32), linked_fixture()[:64]):
            with self.subTest(length=len(data)), self.assertRaises(NexusError):
                static_entry(data)

    def test_no_header_space(self):
        data = bytearray(linked_fixture())
        struct.pack_into("<I", data, 32 + 72 + 48, 300)
        with self.assertRaises(NexusError):
            static_entry(data)

    def test_nonzero_padding_rejected(self):
        data = bytearray(linked_fixture())
        size = struct.unpack_from("<I", data, 20)[0]
        data[32 + size] = 1
        with self.assertRaises(NexusError):
            static_entry(data)

    def test_segment_outside_file(self):
        data = bytearray(static_entry(linked_fixture()))
        struct.pack_into("<Q", data, 32 + 48, len(data) + 1)
        with self.assertRaises(NexusError):
            macho_info(data)

    def test_signed_or_dependent_image_refused(self):
        for command in (0x1D, 0xC, 0x80000034):
            data = bytearray(linked_fixture())
            struct.pack_into("<I", data, 32 + 152 + 24, command)
            with self.subTest(command=command), self.assertRaises(NexusError):
                static_entry(data)
