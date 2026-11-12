"""Read-only host discovery. Installation is an explicit host-specific action."""
from __future__ import annotations

import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

from .core import NexusError, digest


def tool(env: str, names: tuple[str, ...]) -> str | None:
    override = os.environ.get(env)
    if override:
        return shutil.which(override)
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    # Homebrew keeps clang in the keg-only llvm formula; lld is a separate formula.
    for prefix in ("/opt/homebrew/opt/llvm/bin", "/usr/local/opt/llvm/bin",
                   "/opt/homebrew/opt/lld/bin", "/usr/local/opt/lld/bin"):
        if (Path(prefix) / names[0]).is_file():
            return str(Path(prefix) / names[0])
    return None


def missing_hint(name: str, system: str) -> str:
    if system == "Darwin" and name in ("ld64", "lld_link"):
        return "missing; run `brew install lld` (Homebrew's llvm no longer includes LLD)"
    if system == "Darwin" and name == "clang":
        return "missing; run `brew install llvm` and put $(brew --prefix llvm)/bin first on PATH"
    return "missing; see docs/development.md#host-setup"


def tools() -> dict:
    return {
        "git": tool("NEXUS_GIT", ("git",)),
        "qemu": tool("NEXUS_QEMU", ("qemu-system-aarch64",)),
        "clang": tool("NEXUS_CLANG", ("clang", "clang-21", "clang-20", "clang-19", "clang-18")),
        "ld64": tool("NEXUS_LD64", ("ld64.lld", "ld64.lld-21", "ld64.lld-20", "ld64.lld-19", "ld64.lld-18")),
        "lld_link": tool("NEXUS_LLD_LINK", ("lld-link", "lld-link-21", "lld-link-20", "lld-link-19", "lld-link-18")),
    }


def firmware(code: str | None = None, variables: str | None = None) -> tuple[Path | None, Path | None]:
    code = code or os.environ.get("NEXUS_FIRMWARE")
    variables = variables or os.environ.get("NEXUS_VARS")
    if code:
        p = Path(code).expanduser().resolve()
        v = Path(variables).expanduser().resolve() if variables else None
        if not v and p.name.startswith("AAVMF_CODE"):
            v = p.parent / "AAVMF_VARS.fd"
        if not v and (p.parent / "edk2-arm-vars.fd").is_file():
            v = p.parent / "edk2-arm-vars.fd"
        return p, v
    candidates = [
        ("/usr/share/AAVMF/AAVMF_CODE.fd", "/usr/share/AAVMF/AAVMF_VARS.fd"),
        ("/usr/share/edk2/aarch64/QEMU_EFI.fd", "/usr/share/edk2/aarch64/QEMU_VARS.fd"),
    ]
    qemu = tools()["qemu"]
    if qemu:
        share = Path(qemu).resolve().parent.parent / "share/qemu"
        candidates.insert(0, (str(share / "edk2-aarch64-code.fd"), str(share / "edk2-arm-vars.fd")))
    for c, v in candidates:
        if Path(c).is_file() and Path(v).is_file():
            return Path(c), Path(variables).expanduser().resolve() if variables else Path(v)
    return None, Path(variables).expanduser().resolve() if variables else None


def version(path: str) -> str:
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise NexusError(result.stderr.strip()[:300])
        return (result.stdout or result.stderr).splitlines()[0]
    except (OSError, subprocess.TimeoutExpired, IndexError) as error:
        raise NexusError(f"Cannot execute {path}: {error}") from error


def clock_support(qemu_version: str, clock: str) -> tuple[bool, str]:
    if clock == "host":
        return True, "ordinary host clock; validated on QEMU 8.2, 10 and 11"
    match = re.search(r"version (\d+)\.(\d+)", qemu_version)
    supported = clock == "instruction" and match is not None and int(match[1]) >= 10
    return supported, ("instruction clock; validated on QEMU 10" if supported else
                       "instruction clock requires QEMU 10+; QEMU 8.2 can hang before loader entry. Use qemu.clock = 'host' or upgrade QEMU.")


def doctor(code: str | None = None, variables: str | None = None,
           loader: str = "source", runtime_only: bool = False, clock: str = "host") -> dict:
    found = tools()
    c, v = firmware(code, variables)
    checks = []
    qemu_version = ""
    needed = ("qemu",) if runtime_only else ("git", "qemu", "clang", "ld64") + (("lld_link",) if loader == "source" else ())
    for name in needed:
        path = found[name]
        try:
            detail = version(path) if path else missing_hint(name, platform.system())
            ok = bool(path)
        except NexusError as error:
            detail, ok = str(error), False
        checks.append({"name": name, "ok": ok, "path": path, "detail": detail})
        if name == "qemu" and ok:
            qemu_version = detail
    clock_ok, clock_detail = clock_support(qemu_version, clock)
    checks.append({"name": "clock", "ok": clock_ok, "path": None, "detail": clock_detail})
    for name, path in (("firmware", c), ("variables", v)):
        ok = bool(path and path.is_file() and path.stat().st_size == 64 * 1024 * 1024)
        checks.append({"name": name, "ok": ok, "path": str(path) if path else None,
                       "detail": "64 MiB pflash image required; use matching non-Secure-Boot AAVMF/EDK2 images"})
    checks.append({"name": "host", "ok": os.name == "posix", "path": None,
                   "detail": platform.platform() + "; Linux/macOS hosts; TCG guest execution"})
    return {"ready": all(item["ok"] for item in checks), "checks": checks,
            "tools": found, "firmware": str(c) if c else None, "variables": str(v) if v else None,
            "host": {"system": platform.system(), "machine": platform.machine(), "python": platform.python_version()}}


def require_tools(names: tuple[str, ...]) -> dict:
    found = tools()
    missing = [name for name in names if not found[name]]
    if missing:
        raise NexusError("Missing " + ", ".join(missing) + "; run ./nexus doctor and follow docs/development.md.")
    return found


def file_record(path: Path) -> dict:
    return {"path": str(path.resolve()), "sha256": digest(path), "bytes": path.stat().st_size}
