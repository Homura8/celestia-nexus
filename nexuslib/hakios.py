"""The first concrete recipe. HakiOS conventions stay here, outside the runner."""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import sys

from .core import (NexusError, Recorder, digest, fetch_source, implementation_identity, relative_path,
                   verify_source, verified_artifact, write_json)
from .formats import macho_info, static_entry
from .host import file_record, require_tools, version
from .host import doctor as host_doctor
from .qemu import run


def doctor(target: dict, code: str | None = None, variables: str | None = None,
           loader: str = "source") -> dict:
    return host_doctor(code, variables, loader, clock=target["qemu"]["clock"])


def validate_target(target: dict) -> None:
    """Recipe constraints belong here, not in the shared target reader."""
    try:
        extra = set(target) - {"schema", "id", "description", "architecture", "recipe", "source", "kernel", "loader", "qemu"}
        if extra:
            raise NexusError(f"Unknown HakiOS target fields: {sorted(extra)}")
        if target["architecture"] != "aarch64" or target["source"] != "hakios":
            raise NexusError("This recipe is reviewed for the pinned HakiOS AArch64 source only.")
        for name in ("kernel", "loader"):
            item = target[name]
            if set(item) != {"path", "sha256"}:
                raise NexusError(f"{name}: expected path and sha256 only.")
            relative_path(item["path"])
            if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
                raise NexusError(f"{name}.sha256 must be a full SHA-256.")
        qemu = target["qemu"]
        if set(qemu) != {"accel", "clock", "memory_mib", "cpus", "machine", "cpu"}:
            raise NexusError("Unknown/missing QEMU settings; see targets/qemu-virt-xnu/target.toml.")
        if qemu["accel"] != "tcg":
            raise NexusError("This recipe validates TCG only; do not silently substitute HVF/KVM.")
        if qemu["clock"] not in ("instruction", "host"):
            raise NexusError("This recipe supports instruction or host clock only.")
        if type(qemu["memory_mib"]) is not int or not 4096 <= qemu["memory_mib"] <= 8192:
            raise NexusError("HakiOS open needs 4096..8192 MiB for this payload address.")
        if type(qemu["cpus"]) is not int or qemu["cpus"] != 1:
            raise NexusError("This recipe validates one CPU.")
        if qemu["machine"] != "virt,gic-version=3" or qemu["cpu"] != "cortex-a76":
            raise NexusError("This recipe validates virt/GICv3 with cortex-a76.")
    except (KeyError, TypeError) as error:
        raise NexusError(f"Malformed HakiOS target: {error}") from error


def build(root: Path, source_dir: Path, source: dict, target: dict,
          record: Recorder, loader: str = "source", kernel: Path | None = None) -> dict:
    verify_source(source_dir, source)
    needed = ("clang", "ld64") + (("lld_link",) if loader == "source" else ())
    found = require_tools(needed)
    out = record.directory
    kernel_path = kernel.resolve() if kernel else verified_artifact(source_dir, target["kernel"])
    if not kernel_path.is_file():
        raise NexusError(f"No kernel: {kernel_path}")
    kernel_info = macho_info(kernel_path.read_bytes())
    shutil.copyfile(kernel_path, out / "kernel")
    compile_command = [found["clang"], "--target=arm64-apple-macos11", "-Os", "-ffreestanding",
                       "-fno-builtin", "-fno-stack-protector", "-fno-asynchronous-unwind-tables",
                       "-Wall", "-Wextra", "-Werror", "-c", str(root / "guest/probe.c"), "-o", "probe.o"]
    record.command(compile_command, cwd=out)
    record.command([found["ld64"], "-arch", "arm64", "-platform_version", "macos", "11.0", "11.0",
                    "-e", "_start", "-no_uuid", "-no_adhoc_codesign", "-no_fixup_chains",
                    "-headerpad", "0x1000", "-pagezero_size", "0x100000000",
                    "-o", "probe.linked", "probe.o"], cwd=out)
    (out / "probe").write_bytes(static_entry((out / "probe.linked").read_bytes()))
    if loader == "source":
        # These reviewed files contain the freestanding loader; no upstream setup.sh.
        loader_dir = out / "loader-source"
        loader_dir.mkdir()
        for name in ("loader.c", "efi.h", "mkidentity.py"):
            shutil.copyfile(source_dir / "xnuloader" / name, loader_dir / name)
        record.command([sys.executable, str(loader_dir / "mkidentity.py"), "--placeholder"],
                       cwd=out, output=loader_dir / "identity.h")
        record.command([found["clang"], "--target=aarch64-unknown-windows", "-ffreestanding",
                        "-fno-builtin", "-fno-stack-protector", "-fshort-wchar", "-mgeneral-regs-only",
                        "-O1", "-Wall", "-Wextra", "-Wno-unused-parameter", "-c",
                        str(loader_dir / "loader.c"), "-o", "loader.obj"], cwd=out)
        record.command([found["lld_link"], "/subsystem:efi_application", "/entry:efi_main",
                        "/nodefaultlib", "/base:0xA1000000", "/timestamp:0", "/out:loader.efi", "loader.obj"], cwd=out)
    else:
        shutil.copyfile(verified_artifact(source_dir, target["loader"]), out / "loader.efi")
    artifacts = {name: file_record(out / name) for name in ("kernel", "probe", "loader.efi")}
    result = {"schema": 1, "status": "built-not-boot-tested", "target": target["id"],
              "source": source, "loader_mode": loader,
              "kernel_origin": "user-supplied" if kernel else "upstream-prebuilt",
              "kernel_source_correspondence": "not independently verified",
              "implementation": implementation_identity(),
              "inputs": {"probe_source": file_record(root / "guest/probe.c"),
                         "target_configuration": target},
              "tool_versions": {name: version(found[name]) for name in needed},
              "artifacts": artifacts, "kernel_info": kernel_info,
              "probe_info": macho_info((out / "probe").read_bytes())}
    write_json(out / "build.json", result)
    return result


def copy_source(source: Path, destination: Path, boundary: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise NexusError(f"Expected a regular source file: {source}")
    if not destination.resolve().is_relative_to(boundary.resolve()):
        raise NexusError(f"Source overlay escapes the prepared tree: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)


def prepare_kernel(work: Path, sources: dict, target: dict, record: Recorder) -> dict:
    """Materialize and check the real XNU/HFS patch series without an Apple SDK.

    Use reviewed source transformations, not upstream's network/setup scripts.
    Every attempt gets a new tree; an earlier edited experiment is never reset.
    """
    upstream = fetch_source(work, sources[target["source"]], record)
    xnu = fetch_source(work, sources["apple-xnu"], record)
    hfs = fetch_source(work, sources["apple-hfs"], record)
    tree = record.directory / "kernel-source"
    record.command(["git", "clone", "--no-hardlinks", "--no-checkout", str(xnu), str(tree)], cwd=work)
    record.command(["git", "-c", "core.hooksPath=/dev/null", "-C", str(tree), "checkout",
                    "--detach", sources["apple-xnu"]["commit"]], cwd=work)
    patch = upstream / "xnu/hakios.patch"
    record.command(["git", "-C", str(tree), "apply", "--check", "--whitespace=nowarn", str(patch)], cwd=work)
    record.command(["git", "-C", str(tree), "apply", "--whitespace=nowarn", str(patch)], cwd=work)
    copied = {}
    overlay = upstream / "xnu/files"
    for path in sorted(overlay.rglob("*")):
        if path.is_file() or path.is_symlink():
            relative = path.relative_to(overlay)
            copy_source(path, tree / relative, tree)
            copied[str(relative)] = digest(path)
    for listing, source_subdir, target_subdir in (("core.list", "core", "bsd/hfs"),
                                                 ("encodings.list", "hfs_encodings", "bsd/hfs_encodings")):
        for line in (upstream / "xnu/hfs" / listing).read_text().splitlines():
            name = relative_path(line.strip())
            path = hfs / source_subdir / name
            destination = Path(target_subdir) / name
            copy_source(path, tree / destination, tree)
            copied[str(destination)] = digest(path)
    hfs_patch = upstream / "xnu/hfs/hfs.patch"
    record.command(["git", "-C", str(tree), "apply", "--check", str(hfs_patch)], cwd=work)
    record.command(["git", "-C", str(tree), "apply", str(hfs_patch)], cwd=work)
    for line in (upstream / "drivers/map").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        subsystem, destination = line.split()
        relative = relative_path(destination)
        path = upstream / "drivers" / relative_path(subsystem) / relative.name
        copy_source(path, tree / relative, tree)
        copied[str(relative)] = digest(path)
    configuration = record.directory / "qemu.config"
    config_tool = upstream / "tools/hakios-config.py"
    record.command([sys.executable, str(config_tool), "defconfig", "qemu", "-o", str(configuration)], cwd=upstream)
    record.command([sys.executable, str(config_tool), "kernel", "--config", str(configuration),
                    "--tree", str(tree)], cwd=upstream)
    record.command(["git", "-C", str(tree), "diff", "--check"], cwd=work)
    names = record.command(["git", "-C", str(tree), "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=work)
    inventory = {name: digest(tree / name) for name in names.split("\0") if name}
    write_json(record.directory / "tree-manifest.json", inventory)
    for key in (target["source"], "apple-xnu", "apple-hfs"):
        verify_source(work / "sources" / key, sources[key])
    result = {"schema": 1, "status": "prepared-not-compiled", "target": target["id"], "tree": str(tree),
              "sources": {key: sources[key] for key in (target["source"], "apple-xnu", "apple-hfs")},
              "patches": [file_record(patch), file_record(hfs_patch)], "configuration": file_record(configuration),
              "overlay_inputs": copied, "tree_manifest": file_record(record.directory / "tree-manifest.json"),
              "next": "Review the prepared tree; supply an authorised SDK/toolchain before compilation. See docs/development.md#kernel-source."}
    write_json(record.directory / "prepared.json", result)
    return result
