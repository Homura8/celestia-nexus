"""Shared files, process records and pinned source handling; no target boot logic."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import tomllib


class NexusError(Exception):
    """An actionable failure suitable for the command line."""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def implementation_identity() -> dict:
    """Identify executed Nexus code even in a dirty or non-Git checkout."""
    root = Path(__file__).resolve().parent.parent
    paths = [root / "nexus", root / "guest/probe.c", root / "upstreams.lock.toml"]
    paths += sorted((root / "nexuslib").glob("*.py"))
    files = {str(path.relative_to(root)): digest(path) for path in paths}
    checksum = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"sha256": checksum, "files": files}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as stream:
            return tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise NexusError(f"Cannot read {path}: {error}") from error


def relative_path(value: str) -> Path:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value:
        raise NexusError(f"Expected a relative path without '..': {value!r}")
    return path


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", value):
        raise NexusError(f"Invalid identifier: {value!r}")
    return value


def load_target(path: Path) -> dict:
    target = read_toml(path)
    try:
        if target["schema"] != 1:
            raise NexusError("Unsupported target schema; expected 1.")
        identifier(target["id"])
        identifier(target["recipe"])
        identifier(target["source"])
        for field in ("description", "architecture"):
            if not isinstance(target[field], str) or not target[field]:
                raise NexusError(f"Missing {field}.")
    except (KeyError, TypeError) as error:
        raise NexusError(f"Invalid target {path}: missing or malformed {error}") from error
    return target


# Canonical public sources: any HTTPS Git host (GitHub, GitLab, ...), no
# credentials, ports, queries or fragments. Integrity comes from the commit pin.
HTTPS_URL = r"https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?:/[\w.~-]+)+"


def mirror_variable(source_id: str) -> str:
    return "NEXUS_MIRROR_" + source_id.upper().replace("-", "_")


def fetch_url(source: dict) -> str:
    """The lock's canonical URL, or a user-chosen mirror of the same commit.

    A mirror keeps experiments reproducible if an upstream disappears or the
    host is offline. It cannot change what is built: fetch_source still
    requires the locked commit, and artifacts keep their own SHA-256 pins.
    """
    override = os.environ.get(mirror_variable(source["id"]))
    if not override:
        return source["url"]
    if re.fullmatch(HTTPS_URL, override):
        return override
    if override.startswith("file://"):
        override = override[len("file://"):]
    path = Path(override).expanduser()
    if path.is_absolute() and path.is_dir():
        return str(path.resolve())
    raise NexusError(f"{mirror_variable(source['id'])} must be an HTTPS Git URL or an existing "
                     f"absolute local repository path, not {override!r}.")


def active_mirrors(sources: dict[str, dict]) -> dict[str, str]:
    return {key: fetch_url(source) for key, source in sources.items()
            if os.environ.get(mirror_variable(key))}


def load_lock(path: Path) -> dict[str, dict]:
    data = read_toml(path)
    sources = {}
    try:
        if data["schema"] != 1:
            raise NexusError("Unsupported upstream lock schema.")
        for source in data["upstream"]:
            name = identifier(source["id"])
            if name in sources:
                raise NexusError(f"Duplicate upstream {name}.")
            if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
                raise NexusError(f"{name}: pin a full Git commit, not a branch/tag.")
            if not re.fullmatch(HTTPS_URL, source["url"]):
                raise NexusError(f"{name}: expected a canonical HTTPS Git URL without credentials or query.")
            sources[name] = source
    except (KeyError, TypeError) as error:
        raise NexusError(f"Malformed upstream lock: {error}") from error
    return sources


class Recorder:
    """One experiment directory, with commands saved even when a step fails."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=False)
        self.commands: list[dict] = []

    def command(self, argv: list[str], *, cwd: Path, output: Path | None = None,
                timeout: float = 180) -> str:
        argv = [str(arg) for arg in argv]
        entry = {"argv": argv, "cwd": str(cwd), "started_unix": time.time()}
        self.commands.append(entry)
        log = self.directory / f"step-{len(self.commands):02d}.log"
        entry["log"] = log.name
        started = time.monotonic()
        try:
            with subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                  start_new_session=True) as process:
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                    log.write_bytes(stdout + b"\n--- stderr ---\n" + stderr)
                    entry["error"] = "timeout"
                    entry["returncode"] = process.returncode
                    raise NexusError(f"Command timed out after {timeout}s. See {log}")
                except KeyboardInterrupt:
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                    log.write_bytes(stdout + b"\n--- stderr ---\n" + stderr)
                    entry["error"] = "interrupted"
                    entry["returncode"] = process.returncode
                    raise
                entry["returncode"] = process.returncode
                log.write_bytes(stdout + b"\n--- stderr ---\n" + stderr)
                if output is not None and process.returncode == 0:
                    output.write_bytes(stdout)
                if process.returncode:
                    raise NexusError(f"Command exited {process.returncode}: {argv[0]}. See {log}")
                return stdout.decode("utf-8", errors="replace").strip()
        except OSError as error:
            entry["error"] = str(error)
            raise NexusError(f"Cannot run {argv[0]}: {error}") from error
        finally:
            entry["duration_seconds"] = round(time.monotonic() - started, 3)
            write_json(self.directory / "commands.json", self.commands)


def git(source_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-C", str(source_dir), *args],
                                capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise NexusError(f"Git unavailable or timed out: {error}") from error
    if result.returncode:
        raise NexusError(f"Git {args[0]} failed in {source_dir}: {result.stderr.strip()}")
    return result.stdout.strip()


def verify_source(directory: Path, source: dict) -> None:
    if not (directory / ".git").is_dir():
        raise NexusError(f"Missing source {source['id']}; run ./nexus fetch first.")
    if git(directory, "rev-parse", "--show-toplevel") != str(directory.resolve()):
        raise NexusError(f"{directory} is not a separate source checkout.")
    if git(directory, "rev-parse", "HEAD") != source["commit"]:
        raise NexusError(f"{source['id']}: source revision differs from the lock; preserve edits and fetch into a fresh --work directory.")
    if git(directory, "status", "--porcelain", "--untracked-files=all"):
        raise NexusError(f"{source['id']}: source checkout has changes; preserve them before using a fresh --work directory.")


def fetch_source(work: Path, source: dict, record: Recorder) -> Path:
    directory = work / "sources" / source["id"]
    if directory.exists():
        verify_source(directory, source)
        return directory
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = record.directory / ("fetch-" + source["id"])
    # Never run upstream build scripts or recursively fetch submodules here.
    # Publish only a verified checkout. An interrupted first fetch cannot poison
    # the reusable cache; its partial state stays in this attempt's evidence.
    record.command(["git", "init", str(staging)], cwd=work)
    record.command(["git", "-C", str(staging), "remote", "add", "origin", fetch_url(source)], cwd=work)
    record.command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(staging), "fetch",
                    "--depth=1", "origin", source["commit"]], cwd=work, timeout=300)
    record.command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(staging), "checkout",
                    "--detach", "FETCH_HEAD"], cwd=work)
    verify_source(staging, source)
    if directory.exists():
        # Another independent attempt may have finished while this fetched.
        verify_source(directory, source)
    else:
        staging.rename(directory)
    return directory


def verified_artifact(source_dir: Path, item: dict) -> Path:
    path = source_dir / relative_path(item["path"])
    if not path.is_file() or not path.resolve().is_relative_to(source_dir.resolve()):
        raise NexusError(f"Artifact missing or escapes checkout: {path}")
    actual = digest(path)
    if actual != item["sha256"]:
        raise NexusError(f"Hash mismatch for {path}: expected {item['sha256']}, got {actual}")
    return path
