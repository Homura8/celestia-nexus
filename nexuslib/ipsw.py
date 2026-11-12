"""Read-only access to a user-supplied IPSW: manifest identity and selected members.

Only the standard-library zip reader and a bounded DER parser are used. Nothing
here downloads, decrypts or modifies Apple software; unsupported (compressed or
encrypted) payloads are rejected rather than guessed at.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
from pathlib import Path, PurePosixPath
import plistlib
import zipfile

from .core import NexusError


def manifest(path: Path) -> dict:
    try:
        with zipfile.ZipFile(path) as archive:
            data = plistlib.loads(archive.read("BuildManifest.plist"))
    except (OSError, zipfile.BadZipFile, KeyError, plistlib.InvalidFileException) as error:
        raise NexusError(f"{path} is not a readable IPSW with a BuildManifest.plist: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("BuildIdentities"), list):
        raise NexusError(f"{path}: malformed BuildManifest.plist")
    return data


def identity(data: dict, board: str, behavior: str = "Erase") -> dict[str, str]:
    """Paths of each manifest component for one board, e.g. d22ap."""
    for build in data["BuildIdentities"]:
        info = build.get("Info", {})
        if info.get("DeviceClass") == board and info.get("RestoreBehavior") == behavior:
            return {key: value["Info"]["Path"] for key, value in build.get("Manifest", {}).items()
                    if isinstance(value, dict) and isinstance(value.get("Info", {}).get("Path"), str)}
    raise NexusError(f"IPSW has no {behavior} build identity for board {board}.")


def member_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise NexusError(f"Unsafe IPSW member path: {value!r}")
    return str(path)


def extract(path: Path, member: str, destination: Path, expected_size: int | None = None) -> dict:
    """Stream one member to destination; return its size and SHA-256."""
    member = member_name(member)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    hasher = hashlib.sha256()
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo(member)
            if expected_size is not None and info.file_size != expected_size:
                raise NexusError(f"{member}: unexpected size {info.file_size}")
            with archive.open(info) as source, temporary.open("wb") as output:
                while chunk := source.read(8 * 1024 * 1024):
                    hasher.update(chunk)
                    output.write(chunk)
    except KeyError as error:
        raise NexusError(f"IPSW member missing: {member}") from error
    except (OSError, zipfile.BadZipFile) as error:
        temporary.unlink(missing_ok=True)
        raise NexusError(f"Cannot extract {member}: {error}") from error
    temporary.replace(destination)
    return {"member": member, "path": str(destination), "bytes": destination.stat().st_size,
            "sha256": hasher.hexdigest()}


def _der(data: bytes, offset: int) -> tuple[int, int, int]:
    """Return (tag, content start, content end) of one DER element."""
    if offset + 2 > len(data):
        raise NexusError("Truncated DER element.")
    tag = data[offset]
    length = data[offset + 1]
    start = offset + 2
    if length & 0x80:
        count = length & 0x7F
        if not 1 <= count <= 4 or start + count > len(data):
            raise NexusError("Unsupported DER length.")
        length = int.from_bytes(data[start:start + count], "big")
        start += count
    end = start + length
    if end > len(data):
        raise NexusError("DER element exceeds its container.")
    return tag, start, end


def lzfse_decode(data: bytes, size: int) -> bytes:
    """Decode LZFSE with the host's libcompression (macOS); no new dependency."""
    if not 0 < size <= 64 * 1024 * 1024:
        raise NexusError("Implausible LZFSE output size.")
    try:
        library = ctypes.CDLL(ctypes.util.find_library("compression") or "/usr/lib/libcompression.dylib")
    except OSError as error:
        raise NexusError("LZFSE-compressed IM4P needs macOS libcompression; on other hosts extract it "
                         "with `ipsw img4 im4p extract` and pass the result with --device-tree.") from error
    decode = library.compression_decode_buffer
    decode.restype = ctypes.c_size_t
    decode.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t,
                       ctypes.c_void_p, ctypes.c_int]
    output = ctypes.create_string_buffer(size)
    produced = decode(output, size, data, len(data), None, 0x801)  # COMPRESSION_LZFSE
    if produced != size:
        raise NexusError(f"LZFSE decode produced {produced} bytes, expected {size}.")
    return output.raw


def im4p_payload(data: bytes) -> tuple[str, bytes]:
    """Return (four-character type, payload) of an unencrypted IM4P.

    Plain payloads and LZFSE (bvx2) with an IM4P compression record are
    supported; encrypted images (keybags) are rejected.
    """
    tag, start, end = _der(data, 0)
    if tag != 0x30:
        raise NexusError("IM4P is not a DER sequence.")
    fields = []
    cursor = start
    while cursor < end:
        field_tag, field_start, field_end = _der(data, cursor)
        fields.append((field_tag, data[field_start:field_end]))
        cursor = field_end
    if len(fields) < 4 or fields[0] != (0x16, b"IM4P") or fields[1][0] != 0x16 or fields[3][0] != 0x04:
        raise NexusError("Not an IM4P image.")
    kind = fields[1][1].decode("ascii", errors="replace")
    payload = fields[3][1]
    extra = fields[4:]
    if extra and extra[0][0] == 0x04:
        raise NexusError("IM4P payload is encrypted (keybag present); not supported.")
    if payload[:4] == b"bvx2":
        # Compression record: SEQUENCE { INTEGER algorithm (1 = LZFSE), INTEGER size }.
        if len(extra) != 1 or extra[0][0] != 0x30:
            raise NexusError("LZFSE IM4P without a compression record.")
        record = extra[0][1]
        values = []
        cursor = 0
        while cursor < len(record):
            tag, start, end = _der(record, cursor)
            if tag != 0x02:
                raise NexusError("Malformed IM4P compression record.")
            values.append(int.from_bytes(record[start:end], "big"))
            cursor = end
        if len(values) != 2 or values[0] != 1:
            raise NexusError("Unsupported IM4P compression algorithm.")
        return kind, lzfse_decode(payload, values[1])
    if extra or payload[:4] in (b"bvx1", b"bvxn") or payload[:8] == b"complzss":
        raise NexusError("Unsupported IM4P payload encoding.")
    return kind, payload
