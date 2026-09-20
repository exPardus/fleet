#!/usr/bin/env python3
"""Install the reviewed Codex Fleet skill with exact hash reporting."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
from pathlib import Path


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _reject_symlinks(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            raise RuntimeError(f"refusing symlinked install path: {current}")
        if not current.exists():
            break


def install(source: Path, codex_home: Path, *, overwrite: bool = False) -> tuple[str, str]:
    source = source.resolve(strict=True)
    if not source.is_dir() or not (source / "SKILL.md").is_file():
        raise RuntimeError(f"invalid Codex Fleet skill source: {source}")
    destination = codex_home.expanduser().absolute() / "skills" / "fleet"
    _reject_symlinks(destination)
    source_hash = tree_hash(source)
    if destination.exists():
        destination_hash = tree_hash(destination)
        if destination_hash == source_hash:
            return source_hash, destination_hash
        if not overwrite:
            raise RuntimeError(
                f"destination differs ({destination_hash}); rerun with --overwrite")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix=".fleet-skill-", dir=destination.parent) as temporary:
        staged = Path(temporary) / "fleet"
        shutil.copytree(source, staged)
        if destination.exists():
            backup = destination.with_name(f".{destination.name}.old.{os.getpid()}")
            os.replace(destination, backup)
            try:
                os.replace(staged, destination)
            except BaseException:
                os.replace(backup, destination)
                raise
            shutil.rmtree(backup)
        else:
            os.replace(staged, destination)
    return source_hash, tree_hash(destination)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=(
        Path(__file__).resolve().parents[1] / "skills" / "codex-fleet"))
    parser.add_argument("--codex-home", type=Path, default=Path(
        os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    try:
        source_hash, destination_hash = install(
            args.source, args.codex_home, overwrite=args.overwrite)
    except (OSError, RuntimeError) as exc:
        print(f"install_codex_skill: {exc}", file=sys.stderr)
        return 1
    print(f"source_sha256={source_hash}")
    print(f"destination_sha256={destination_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
