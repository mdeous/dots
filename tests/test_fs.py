from __future__ import annotations

import os
from pathlib import Path

import pytest

from dots.errors import FsError
from dots.fs import atomic_copy, atomic_symlink, ensure_parent_dir, is_inside, safe_unlink


def raise_oserror(*args: object, **kwargs: object) -> None:
    raise OSError("simulated failure")


class TestIsInside:
    def test_child_inside_parent(self, tmp_path: Path) -> None:
        child = tmp_path / "sub" / "file.txt"
        assert is_inside(child, tmp_path)

    def test_child_is_parent(self, tmp_path: Path) -> None:
        assert is_inside(tmp_path, tmp_path)

    def test_child_outside_parent(self, tmp_path: Path) -> None:
        assert not is_inside(Path("/somewhere/else"), tmp_path)

    def test_relative_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "sub").mkdir()
        assert is_inside(Path("sub/file"), tmp_path)

    def test_symlink_not_followed(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        real_file = outside / "real.txt"
        real_file.write_text("data")

        inside = tmp_path / "inside"
        inside.mkdir()
        link = inside / "link"
        link.symlink_to(real_file)

        assert is_inside(link, inside)
        assert not is_inside(link, outside)


class TestEnsureParentDir:
    def test_creates_nested_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "a" / "b" / "c" / "file.txt"
        ensure_parent_dir(target)
        assert (tmp_path / "a" / "b" / "c").is_dir()

    def test_existing_dir_ok(self, tmp_path: Path) -> None:
        (tmp_path / "existing").mkdir()
        ensure_parent_dir(tmp_path / "existing" / "file.txt")

    @pytest.mark.skipif(os.getuid() == 0, reason="root bypasses permissions")
    def test_permission_error_raises_fserror(self, tmp_path: Path) -> None:
        blocked = tmp_path / "blocked"
        blocked.mkdir(mode=0o444)
        try:
            with pytest.raises(FsError):
                ensure_parent_dir(blocked / "sub" / "file.txt")
        finally:
            blocked.chmod(0o755)


class TestAtomicSymlink:
    def test_creates_new_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("content")
        link = tmp_path / "link"

        atomic_symlink(target, link)

        assert link.is_symlink()
        assert link.resolve() == target.resolve()

    def test_replaces_existing_file(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("new")
        existing = tmp_path / "existing.txt"
        existing.write_text("old")

        atomic_symlink(target, existing)

        assert existing.is_symlink()
        assert existing.read_text() == "new"

    def test_replaces_existing_symlink(self, tmp_path: Path) -> None:
        old_target = tmp_path / "old.txt"
        old_target.write_text("old")
        new_target = tmp_path / "new.txt"
        new_target.write_text("new")
        link = tmp_path / "link"
        link.symlink_to(old_target)

        atomic_symlink(new_target, link)

        assert link.resolve() == new_target.resolve()
        assert link.read_text() == "new"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "new_dir" / "sub" / "link"

        atomic_symlink(target, link)

        assert link.is_symlink()

    def test_no_leftover_tmp_files(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "link"

        atomic_symlink(target, link)

        assert not any(tmp_path.glob("*.tmp"))

    def test_symlink_to_failure_raises_fserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "link"

        monkeypatch.setattr(Path, "symlink_to", raise_oserror)

        with pytest.raises(FsError):
            atomic_symlink(target, link)

    def test_replace_failure_raises_fserror_and_cleans_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "target.txt"
        target.write_text("data")
        link = tmp_path / "link"

        monkeypatch.setattr(Path, "replace", raise_oserror)

        with pytest.raises(FsError):
            atomic_symlink(target, link)

        assert not any(tmp_path.glob("*.tmp"))


class TestAtomicCopy:
    def test_copies_file_content(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("hello world")
        dst = tmp_path / "dst.txt"

        atomic_copy(src, dst)

        assert dst.read_text() == "hello world"

    def test_preserves_metadata(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("data")
        os.utime(src, (1000000, 1000000))

        dst = tmp_path / "dst.txt"
        atomic_copy(src, dst)

        assert abs(dst.stat().st_mtime - 1000000) < 2

    def test_replaces_existing_file(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("new content")
        dst = tmp_path / "dst.txt"
        dst.write_text("old content")

        atomic_copy(src, dst)

        assert dst.read_text() == "new content"

    def test_source_untouched(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("original")
        dst = tmp_path / "dst.txt"

        atomic_copy(src, dst)

        assert src.read_text() == "original"

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("data")
        dst = tmp_path / "new" / "deep" / "dst.txt"

        atomic_copy(src, dst)

        assert dst.read_text() == "data"

    def test_nonexistent_source_raises_fserror(self, tmp_path: Path) -> None:
        src = tmp_path / "nope.txt"
        dst = tmp_path / "dst.txt"

        with pytest.raises(FsError):
            atomic_copy(src, dst)

    def test_no_leftover_tmp_files(self, tmp_path: Path) -> None:
        src = tmp_path / "src.txt"
        src.write_text("data")
        dst = tmp_path / "dst.txt"

        atomic_copy(src, dst)

        assert not any(tmp_path.glob("*.tmp"))

    def test_replace_failure_raises_fserror_and_cleans_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        src = tmp_path / "src.txt"
        src.write_text("data")
        dst = tmp_path / "dst.txt"

        monkeypatch.setattr(Path, "replace", raise_oserror)

        with pytest.raises(FsError):
            atomic_copy(src, dst)

        assert not any(tmp_path.glob("*.tmp"))


class TestSafeUnlink:
    def test_removes_existing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("bye")

        safe_unlink(f)

        assert not f.exists()

    def test_removes_symlink(self, tmp_path: Path) -> None:
        target = tmp_path / "target.txt"
        target.write_text("keep me")
        link = tmp_path / "link"
        link.symlink_to(target)

        safe_unlink(link)

        assert not link.exists()
        assert target.read_text() == "keep me"

    def test_missing_file_ok(self, tmp_path: Path) -> None:
        safe_unlink(tmp_path / "nonexistent")

    def test_oserror_raises_fserror(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        f = tmp_path / "file.txt"
        f.write_text("data")

        monkeypatch.setattr(Path, "unlink", raise_oserror)

        with pytest.raises(FsError):
            safe_unlink(f)
