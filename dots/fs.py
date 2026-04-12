from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from dots.errors import FsError

TMP_TEMPLATE = ".{name}.dots-{pid}.tmp"


def tmp_path(target: Path) -> Path:
    return target.with_name(TMP_TEMPLATE.format(name=target.name, pid=os.getpid()))


def is_inside(child: Path, parent: Path) -> bool:
    """
    Return True if ``child`` is at or under ``parent``.

    Both paths are made absolute, but symlinks are NOT followed.
    """
    return child.absolute().is_relative_to(parent.absolute())


def ensure_parent_dir(path: Path) -> None:
    """
    Create all missing parent directories of ``path``.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FsError(f"failed to create parent directory for {path}", path) from e


def atomic_symlink(target: Path, link: Path) -> None:
    """
    Atomically create or replace a symlink at ``link`` pointing to ``target``.

    Works whether ``link`` is currently missing, a regular file, or an existing
    symlink.
    """
    ensure_parent_dir(link)
    tmp = tmp_path(link)
    try:
        tmp.symlink_to(target)
    except OSError as e:
        raise FsError(f"failed to create symlink at {link}", link) from e
    try:
        tmp.replace(link)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to install symlink at {link}", link) from e


def atomic_copy(src: Path, dst: Path) -> None:
    """
    Atomically install a copy of ``src`` at ``dst``.

    Copies to a sibling temp next to ``dst`` then ``os.replace`` to commit.
    ``src`` is never touched - the caller decides whether to remove it.
    On any failure, ``dst`` is left in its previous state.
    """
    ensure_parent_dir(dst)
    tmp = tmp_path(dst)
    try:
        shutil.copy2(src, tmp)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to stage copy at {dst}", dst) from e
    try:
        tmp.replace(dst)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to install file at {dst}", dst) from e


def atomic_write(dst: Path, data: bytes) -> None:
    """
    Atomically write ``data`` to ``dst``.

    Writes to a sibling temp file then ``os.replace`` to commit.
    On failure, ``dst`` is left in its previous state.
    """
    ensure_parent_dir(dst)
    tmp = tmp_path(dst)
    try:
        tmp.write_bytes(data)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to write to {dst}", dst) from e
    try:
        tmp.replace(dst)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to install file at {dst}", dst) from e


def safe_unlink(path: Path) -> None:
    """
    Remove ``path`` if it exists. Tolerant of missing paths.
    """
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        raise FsError(f"failed to remove {path}", path) from e
