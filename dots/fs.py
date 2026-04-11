from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

from dots.errors import FsError

_TMP_TEMPLATE = ".{name}.dots-{pid}.tmp"


def _tmp_path(target: Path) -> Path:
    return target.with_name(_TMP_TEMPLATE.format(name=target.name, pid=os.getpid()))


def is_inside(child: Path, parent: Path) -> bool:
    """Return True if ``child`` is at or under ``parent``.

    Both paths are made absolute (prepending cwd if relative) but symlinks are
    NOT followed. Call ``Path.resolve()`` before passing if you need
    symlink-following containment.
    """
    return child.absolute().is_relative_to(parent.absolute())


def ensure_parent_dir(path: Path) -> None:
    """Create all missing parent directories of ``path``."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise FsError(f"failed to create parent directory for {path}", path, cause=e) from e


def atomic_symlink(target: Path, link: Path) -> None:
    """Atomically create or replace a symlink at ``link`` pointing to ``target``.

    Works whether ``link`` is currently missing, a regular file, or an existing
    symlink. At every moment an observer will see either the previous state or
    the new symlink — never a missing path.
    """
    ensure_parent_dir(link)
    tmp = _tmp_path(link)
    try:
        tmp.symlink_to(target)
    except OSError as e:
        raise FsError(f"failed to create symlink at {link}", link, cause=e) from e
    try:
        tmp.replace(link)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to install symlink at {link}", link, cause=e) from e


def atomic_copy(src: Path, dst: Path) -> None:
    """Atomically install a copy of ``src`` at ``dst``.

    Copies to a sibling temp next to ``dst`` then ``os.replace`` to commit.
    ``src`` is never touched — the caller decides whether to remove it.
    On any failure, ``dst`` is left in its previous state.
    """
    ensure_parent_dir(dst)
    tmp = _tmp_path(dst)
    try:
        shutil.copy2(src, tmp)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to stage copy at {dst}", dst, cause=e) from e
    try:
        tmp.replace(dst)
    except OSError as e:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise FsError(f"failed to install file at {dst}", dst, cause=e) from e


def safe_unlink(path: Path) -> None:
    """Remove ``path`` if it exists. Tolerant of missing paths."""
    try:
        path.unlink(missing_ok=True)
    except OSError as e:
        raise FsError(f"failed to remove {path}", path, cause=e) from e
