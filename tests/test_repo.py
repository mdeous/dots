from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from git.exc import GitError

from dots.errors import (
    AlreadyInRepoError,
    FsError,
    InvalidTargetError,
    NotInHomeError,
    NotInRepoError,
    RepoError,
)
from dots.repo import DotRepository

from .conftest import StubUI


class TestValidateAddable:
    def test_nonexistent_file(self, dot_repo: DotRepository, fake_home: Path) -> None:
        with pytest.raises(InvalidTargetError, match="file not found"):
            dot_repo.add(fake_home / "nope.txt")

    def test_directory(self, dot_repo: DotRepository, fake_home: Path) -> None:
        d = fake_home / "somedir"
        d.mkdir()
        with pytest.raises(InvalidTargetError, match="not a regular file"):
            dot_repo.add(d)

    def test_symlink(self, dot_repo: DotRepository, fake_home: Path) -> None:
        target = fake_home / "real.txt"
        target.write_text("data")
        link = fake_home / "link"
        link.symlink_to(target)
        with pytest.raises(InvalidTargetError, match="cannot add a symlink"):
            dot_repo.add(link)

    def test_already_tracked_symlink(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "tracked.txt"
        repo_file.write_text("data")
        link = fake_home / "tracked.txt"
        link.symlink_to(repo_file)
        with pytest.raises(AlreadyInRepoError):
            dot_repo.add(link)

    def test_file_outside_home(self, dot_repo: DotRepository, tmp_path: Path) -> None:
        outside = tmp_path / "outside.txt"
        outside.write_text("data")
        with pytest.raises(NotInHomeError):
            dot_repo.add(outside)

    def test_file_inside_repo(self, dot_repo: DotRepository, fake_repo: Path) -> None:
        repo_file = fake_repo / "inside.txt"
        repo_file.write_text("data")
        with pytest.raises(InvalidTargetError, match="already inside the repository"):
            dot_repo.add(repo_file)


class TestAdd:
    def test_copies_and_symlinks(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        config_dir = fake_home / ".config"
        config_dir.mkdir()
        target = config_dir / "app.conf"
        target.write_text("key=value")

        dot_repo.add(target)

        repo_file = fake_repo / ".config" / "app.conf"
        assert repo_file.exists()
        assert repo_file.read_text() == "key=value"
        assert target.is_symlink()
        assert target.resolve() == repo_file.resolve()
        assert target.read_text() == "key=value"

    def test_preserves_nested_dirs(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        nested = fake_home / "a" / "b" / "c"
        nested.mkdir(parents=True)
        target = nested / "file.txt"
        target.write_text("deep")

        dot_repo.add(target)

        assert (fake_repo / "a" / "b" / "c" / "file.txt").read_text() == "deep"

    def test_rollback_on_symlink_failure(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        target = fake_home / "important.conf"
        target.write_text("precious data")

        with patch("dots.fs.atomic_symlink", side_effect=FsError("fail", target)), pytest.raises(FsError):
            dot_repo.add(target)

        assert target.read_text() == "precious data"
        assert not target.is_symlink()
        assert not (fake_repo / "important.conf").exists()


class TestRemove:
    def _setup_tracked_file(
        self, fake_home: Path, fake_repo: Path, relpath: str, content: str = "data"
    ) -> tuple[Path, Path]:
        repo_file = fake_repo / relpath
        repo_file.parent.mkdir(parents=True, exist_ok=True)
        repo_file.write_text(content)
        home_file = fake_home / relpath
        home_file.parent.mkdir(parents=True, exist_ok=True)
        home_file.symlink_to(repo_file)
        return home_file, repo_file

    def test_restores_file(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        home_file, repo_file = self._setup_tracked_file(fake_home, fake_repo, ".config/app.conf", content="restored")

        dot_repo.remove(home_file)

        assert not home_file.is_symlink()
        assert home_file.is_file()
        assert home_file.read_text() == "restored"
        assert not repo_file.exists()

    def test_regular_file_raises(self, dot_repo: DotRepository, fake_home: Path) -> None:
        home_file = fake_home / "file.txt"
        home_file.write_text("data")

        with pytest.raises(NotInRepoError):
            dot_repo.remove(home_file)

    def test_not_a_symlink_at_home_raises(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "file.txt"
        repo_file.write_text("data")
        home_file = fake_home / "file.txt"
        home_file.write_text("different")

        with pytest.raises(InvalidTargetError, match="expected symlink"):
            dot_repo.remove(repo_file)

    def test_wrong_symlink_target_raises(self, dot_repo: DotRepository, fake_home: Path, tmp_path: Path) -> None:
        outside = tmp_path / "elsewhere.txt"
        outside.write_text("data")
        link = fake_home / "link.txt"
        link.symlink_to(outside)

        with pytest.raises(NotInRepoError):
            dot_repo.remove(link)

    def test_cleans_empty_parent_dirs(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        home_file, _ = self._setup_tracked_file(fake_home, fake_repo, "a/b/file.txt")

        dot_repo.remove(home_file)

        assert not (fake_repo / "a" / "b").exists()
        assert not (fake_repo / "a").exists()

    def test_preserves_nonempty_parent_dirs(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        home_file, _ = self._setup_tracked_file(fake_home, fake_repo, "a/b/file.txt")
        (fake_repo / "a" / "other.txt").write_text("keep me")

        dot_repo.remove(home_file)

        assert not (fake_repo / "a" / "b").exists()
        assert (fake_repo / "a").is_dir()
        assert (fake_repo / "a" / "other.txt").read_text() == "keep me"


class TestSync:
    def test_creates_missing_symlinks(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("alias ls='ls --color'")

        dot_repo.sync()

        link = fake_home / "bashrc"
        assert link.is_symlink()
        assert link.resolve() == repo_file.resolve()

    def test_correct_symlink_unchanged(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("data")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)

        dot_repo.sync()

        assert link.is_symlink()
        assert link.resolve() == repo_file.resolve()

    def test_wrong_symlink_force_relink(
        self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path, tmp_path: Path
    ) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("repo version")
        wrong_target = tmp_path / "wrong.txt"
        wrong_target.write_text("wrong")
        link = fake_home / "bashrc"
        link.symlink_to(wrong_target)

        dot_repo.sync(force_relink=True)

        assert link.resolve() == repo_file.resolve()

    def test_conflict_force_add(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("old repo content")
        local_file = fake_home / "bashrc"
        local_file.write_text("local version")

        dot_repo.sync(force_add=True)

        assert repo_file.read_text() == "local version"
        assert local_file.is_symlink()

    def test_conflict_force_link(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("repo version")
        local_file = fake_home / "bashrc"
        local_file.write_text("local version")

        dot_repo.sync(force_link=True)

        assert local_file.is_symlink()
        assert local_file.read_text() == "repo version"

    def test_list_only_no_modification(self, dot_repo: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        repo_file = fake_repo / "bashrc"
        repo_file.write_text("data")

        dot_repo.sync(list_only=True)

        assert not (fake_home / "bashrc").exists()

    def test_skips_ignored_files(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = DotRepository(
            path=fake_repo,
            home=fake_home,
            ignored=("*.swp",),
            git=None,
            ui=stub_ui,
        )
        (fake_repo / "file.swp").write_text("swap")
        (fake_repo / "real.conf").write_text("config")

        repo.sync()

        assert not (fake_home / "file.swp").exists()
        assert (fake_home / "real.conf").is_symlink()


class TestIsIgnored:
    def _repo(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI, patterns: tuple[str, ...]) -> DotRepository:
        return DotRepository(path=fake_repo, home=fake_home, ignored=patterns, git=None, ui=stub_ui)

    def test_filename_pattern_matches(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ("*.swp",))
        assert repo.is_ignored(Path(".config/vim/file.swp"))

    def test_filename_pattern_no_match(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ("*.swp",))
        assert not repo.is_ignored(Path(".config/vim/file.txt"))

    def test_anchored_pattern_matches(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ("/.config/secret",))
        assert repo.is_ignored(Path(".config/secret"))

    def test_anchored_pattern_no_match_elsewhere(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ("/.config/secret",))
        assert not repo.is_ignored(Path("other/secret"))

    def test_anchored_glob_pattern(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ("/.config/*.key",))
        assert repo.is_ignored(Path(".config/my.key"))

    def test_empty_ignored(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        repo = self._repo(fake_home, fake_repo, stub_ui, ())
        assert not repo.is_ignored(Path("anything"))


class TestIterRepoFiles:
    def test_yields_regular_files(self, dot_repo: DotRepository, fake_repo: Path) -> None:
        (fake_repo / "a.txt").write_text("a")
        (fake_repo / "b.txt").write_text("b")
        sub = fake_repo / "sub"
        sub.mkdir()
        (sub / "c.txt").write_text("c")

        files = list(dot_repo.iter_repo_files())

        relpaths = {f.relative_to(fake_repo).as_posix() for f in files}
        assert relpaths == {"a.txt", "b.txt", "sub/c.txt"}

    def test_skips_git_directory(self, dot_repo: DotRepository, fake_repo: Path) -> None:
        git_dir = fake_repo / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (fake_repo / ".git" / "config").write_text("gitconfig")
        (git_dir / "abc").write_text("obj")
        (fake_repo / "real.txt").write_text("real")

        files = list(dot_repo.iter_repo_files())

        relpaths = {f.relative_to(fake_repo).as_posix() for f in files}
        assert relpaths == {"real.txt"}

    def test_results_are_sorted(self, dot_repo: DotRepository, fake_repo: Path) -> None:
        for name in ["z.txt", "a.txt", "m.txt"]:
            (fake_repo / name).write_text(name)

        files = list(dot_repo.iter_repo_files())
        names = [f.name for f in files]
        assert names == sorted(names)


class TestGitCommit:
    def test_commit_called_on_add(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        mock_git = MagicMock()
        repo = DotRepository(path=fake_repo, home=fake_home, ignored=(), git=mock_git, ui=stub_ui)

        target = fake_home / "file.txt"
        target.write_text("data")
        repo.add(target)

        mock_git.git.add.assert_called_with(all=True)
        mock_git.git.commit.assert_called_once()
        call_msg = mock_git.git.commit.call_args[1]["message"]
        assert "[dots]" in call_msg
        assert "file.txt" in call_msg

    def test_git_failure_is_non_fatal(self, fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> None:
        mock_git = MagicMock()
        mock_git.git.commit.side_effect = GitError("fail")
        repo = DotRepository(path=fake_repo, home=fake_home, ignored=(), git=mock_git, ui=stub_ui)

        target = fake_home / "file.txt"
        target.write_text("data")
        repo.add(target)

        assert target.is_symlink()
        assert (fake_repo / "file.txt").exists()

    def test_git_none_works(self, dot_repo: DotRepository, fake_home: Path) -> None:
        target = fake_home / "file.txt"
        target.write_text("data")
        dot_repo.add(target)
        assert target.is_symlink()


class TestLoad:
    def test_valid_config(self, fake_repo: Path, tmp_path: Path, stub_ui: StubUI) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text(f"[DEFAULT]\nrepo_dir = {fake_repo}\n")

        repo = DotRepository.load(cfg, stub_ui)

        assert repo.path == fake_repo

    def test_missing_repo_raises(self, tmp_path: Path, stub_ui: StubUI) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = /nonexistent/repo\n")

        with pytest.raises(RepoError, match="no dots repository found"):
            DotRepository.load(cfg, stub_ui)
