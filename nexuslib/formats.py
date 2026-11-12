"""Strict readers for the binary interfaces used by the first real target."""
from __future__ import annotations

import struct
from .core import NexusError


def macho_info(data: bytes) -> dict:
    """Validate a thin ARM64 executable and bound every segment/load command."""
    if len(data) < 32:
        raise NexusError("Truncated Mach-O header.")
    magic, cpu, subtype, kind, count, size, flags, _ = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF or cpu != 0x0100000C or kind != 2:
        raise NexusError("Expected a thin little-endian ARM64 MH_EXECUTE Mach-O.")
    if size > len(data) - 32 or count > size // 8:
        raise NexusError("Mach-O load commands exceed the file.")
    cursor = 32
    segments = []
    for _ in range(count):
        if cursor + 8 > 32 + size:
            raise NexusError("Truncated Mach-O load command.")
        cmd, length = struct.unpack_from("<II", data, cursor)
        if length < 8 or length % 8 or cursor + length > 32 + size:
            raise NexusError("Invalid Mach-O load command length.")
        if cmd == 0x19:
            if length < 72:
                raise NexusError("Truncated LC_SEGMENT_64.")
            name, vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<16s4Q", data, cursor + 8)
            if fileoff > len(data) or filesize > len(data) - fileoff or filesize > vmsize:
                raise NexusError("Mach-O segment exceeds file or virtual size.")
            segments.append({"name": name.split(b"\0")[0].decode("ascii", errors="replace"),
                             "vmaddr": hex(vmaddr), "vmsize": vmsize, "filesize": filesize})
        if cmd in (0xC, 0xE, 0x18 | 0x80000000, 0x1F | 0x80000000, 0x20, 0x23 | 0x80000000):
            raise NexusError("The open guest must be static: found dyld/dylib load commands.")
        cursor += length
    if cursor != 32 + size or not segments:
        raise NexusError("Inconsistent Mach-O command table or no segments.")
    return {"format": "Mach-O ARM64", "cpu_subtype": subtype, "flags": flags, "segments": segments}


def payload_pack(items: dict[str, bytes]) -> bytes:
    """XNUP wire format from HakiOS xnuloader/loader.c, not a generic boot ABI.

    Header: magic + body size; entry: 16-byte name + size + reserved + padded data.
    The 24-byte entry header itself is NOT 16-byte aligned. The loader relies on it.
    """
    body = bytearray()
    for name, data in items.items():
        try:
            encoded = name.encode("ascii")
        except UnicodeEncodeError as error:
            raise NexusError("XNUP names must be ASCII.") from error
        if not encoded or len(encoded) > 15 or b"\0" in encoded:
            raise NexusError(f"XNUP name must contain 1..15 non-NUL ASCII bytes: {name!r}")
        if len(data) > 0xFFFFFFFF:
            raise NexusError("XNUP item too large.")
        body += struct.pack("<16sII", encoded, len(data), 0)
        body += data + bytes(-len(data) % 16)
    body += bytes(24)
    if len(body) + 8 > 0x04000000:
        raise NexusError("XNUP payload exceeds this loader's 64 MiB reservation.")
    return struct.pack("<II", 0x50554E58, len(body)) + body


def static_entry(data: bytes) -> bytes:
    """Turn our dependency-free LLD fixture into a static XNU executable.

    LLD 19's Mach-O -static is unimplemented. Replace LC_MAIN/dyld with
    LC_UNIXTHREAD (ARM_THREAD_STATE64) in reserved header space. This operates
    only on our own linked probe, never an Apple executable or kernel.
    Layout: XNU osfmk/mach/arm/_structs.h and thread_status.h, xnu-8796.121.2.
    """
    if len(data) < 32 or struct.unpack_from("<4I", data) != (0xFEEDFACF, 0x0100000C, 0, 2):
        raise NexusError("Static entry conversion requires our thin ARM64 executable.")
    count, command_size = struct.unpack_from("<II", data, 16)
    if command_size > len(data) - 32 or count > command_size // 8:
        raise NexusError("Truncated command table.")
    commands = []
    cursor = 32
    text_base = entry_offset = None
    first_section = len(data)
    for _ in range(count):
        if cursor + 8 > 32 + command_size:
            raise NexusError("Truncated load command.")
        cmd, size = struct.unpack_from("<II", data, cursor)
        if size < 8 or size % 8 or cursor + size > 32 + command_size:
            raise NexusError("Invalid load command.")
        command = data[cursor:cursor + size]
        if cmd == 0x19:
            if size < 72:
                raise NexusError("Truncated segment.")
            name = command[8:24].split(b"\0")[0]
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<4Q", command, 24)
            sections = struct.unpack_from("<I", command, 64)[0]
            if 72 + sections * 80 != size or fileoff + filesize > len(data) or filesize > vmsize:
                raise NexusError("Invalid segment or section table.")
            if name == b"__TEXT":
                if fileoff != 0:
                    raise NexusError("Expected __TEXT at file offset zero.")
                text_base = vmaddr
            for section in range(sections):
                offset = struct.unpack_from("<I", command, 72 + section * 80 + 48)[0]
                if offset:
                    first_section = min(first_section, offset)
        if cmd == 0x80000028:
            if size != 24 or entry_offset is not None:
                raise NexusError("Invalid/duplicate LC_MAIN.")
            entry_offset = struct.unpack_from("<Q", command, 8)[0]
        elif cmd == 0xE:  # LC_LOAD_DYLINKER is emitted by LLD even without dependencies.
            pass
        else:
            if cmd in (0xC, 0x18 | 0x80000000, 0x1F | 0x80000000, 0x20, 0x23 | 0x80000000,
                       0x1D, 0x80000034, 5):
                raise NexusError("Cannot convert a dylib-dependent, signed, chained-fixup or thread-state image.")
            if cmd == 0x80000022:
                if size != 48 or any(struct.unpack_from("<8I", command, 8)):
                    raise NexusError("Static probe must have no dyld rebases or bindings.")
            commands.append(command)
        cursor += size
    if cursor != 32 + command_size or text_base is None or entry_offset is None:
        raise NexusError("Missing __TEXT/LC_MAIN or inconsistent command table.")
    if not first_section <= entry_offset < len(data):
        raise NexusError("Entry point is outside the probe's code.")
    state = bytearray(272)
    struct.pack_into("<Q", state, 256, text_base + entry_offset)
    commands.append(struct.pack("<4I", 5, 288, 6, 68) + state)
    table = b"".join(commands)
    end = max(command_size, len(table)) + 32
    if end > first_section or any(data[32 + command_size:end]):
        raise NexusError("Insufficient zero-filled header padding; link with -headerpad 0x1000.")
    output = bytearray(data)
    struct.pack_into("<II", output, 16, len(commands), len(table))
    # MH_NOUNDEFS, no MH_DYLDLINK/PIE/TWOLEVEL: the kernel starts this directly.
    struct.pack_into("<I", output, 24, 1)
    output[32:end] = table + bytes(end - 32 - len(table))
    macho_info(output)
    return bytes(output)


def payload_unpack(data: bytes) -> dict[str, bytes]:
    if len(data) < 32 or len(data) > 0x04000000:
        raise NexusError("Invalid XNUP size.")
    magic, size = struct.unpack_from("<II", data)
    if magic != 0x50554E58 or size != len(data) - 8:
        raise NexusError("Bad XNUP magic or body length.")
    cursor = 8
    items = {}
    while cursor + 24 <= len(data):
        name, size, reserved = struct.unpack_from("<16sII", data, cursor)
        cursor += 24
        if not any(name):
            if size or reserved or cursor != len(data):
                raise NexusError("Invalid XNUP terminator/trailing data.")
            return items
        if b"\0" not in name or reserved:
            raise NexusError("Invalid XNUP entry header.")
        try:
            key = name.split(b"\0")[0].decode("ascii")
        except UnicodeDecodeError as error:
            raise NexusError("Non-ASCII XNUP name.") from error
        if not key or key in items or cursor + size + (-size % 16) > len(data):
            raise NexusError("Duplicate, empty or out-of-bounds XNUP entry.")
        items[key] = data[cursor:cursor + size]
        if any(data[cursor + size:cursor + size + (-size % 16)]):
            raise NexusError("Nonzero XNUP padding.")
        cursor += size + (-size % 16)
    raise NexusError("Missing XNUP terminator.")


def macho_symbols(data: bytes, names: set[str]) -> dict[str, int]:
    """Values of selected external/defined symbols from a 64-bit Mach-O LC_SYMTAB."""
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != 0xFEEDFACF:
        raise NexusError("Expected a 64-bit little-endian Mach-O.")
    count, size = struct.unpack_from("<II", data, 16)
    if size > len(data) - 32:
        raise NexusError("Mach-O load commands exceed the file.")
    cursor = 32
    for _ in range(count):
        if cursor + 8 > 32 + size:
            raise NexusError("Truncated Mach-O load command.")
        cmd, length = struct.unpack_from("<II", data, cursor)
        if length < 8 or cursor + length > 32 + size:
            raise NexusError("Invalid Mach-O load command length.")
        if cmd == 0x2:  # LC_SYMTAB
            symoff, nsyms, stroff, strsize = struct.unpack_from("<4I", data, cursor + 8)
            if symoff + nsyms * 16 > len(data) or stroff + strsize > len(data):
                raise NexusError("Mach-O symbol table exceeds the file.")
            found = {}
            for index in range(nsyms):
                strx, kind, _, _, value = struct.unpack_from("<IBBHQ", data, symoff + index * 16)
                if kind & 0xE0 or kind & 0x0E != 0x0E or strx >= strsize:
                    continue  # debugging entries and undefined symbols
                end = data.find(b"\0", stroff + strx, stroff + strsize)
                name = data[stroff + strx:end].decode("ascii", errors="replace")
                if name in names:
                    found[name] = value
            missing = names - set(found)
            if missing:
                raise NexusError(f"Kernel lacks symbols: {sorted(missing)}")
            return found
        cursor += length
    raise NexusError("Mach-O has no symbol table.")
