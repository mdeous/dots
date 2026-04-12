from __future__ import annotations

from pathlib import Path

import pytest
from git import Repo as GitRepo

from dots.repo import DotRepository

from .conftest import StubUI


@pytest.fixture()
def git_repo(fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> DotRepository:
    git = GitRepo.init(fake_repo)
    git.config_writer().set_value("user", "name", "Test").release()
    git.config_writer().set_value("user", "email", "test@test").release()
    # initial commit so HEAD exists
    (fake_repo / ".gitkeep").write_text("")
    git.index.add([".gitkeep"])
    git.index.commit("[dots] init")
    return DotRepository(
        path=fake_repo,
        home=fake_home,
        ignored=(),
        git=git,
        ui=stub_ui,
    )


class TestDirtyRelpaths:
    def test_clean_repo(self, git_repo: DotRepository) -> None:
        assert git_repo._dirty_relpaths() == frozenset()

    def test_modified_file(self, git_repo: DotRepository) -> None:
        tracked = git_repo.path / "bashrc"
        tracked.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")

        tracked.write_text("modified")

        assert "bashrc" in git_repo._dirty_relpaths()

    def test_staged_file(self, git_repo: DotRepository) -> None:
        tracked = git_repo.path / "bashrc"
        tracked.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")

        tracked.write_text("staged change")
        git_repo.git.index.add(["bashrc"])

        assert "bashrc" in git_repo._dirty_relpaths()

    def test_untracked_file(self, git_repo: DotRepository) -> None:
        (git_repo.path / "newfile").write_text("hello")

        assert "newfile" in git_repo._dirty_relpaths()

    def test_no_git(self, dot_repo: DotRepository) -> None:
        assert dot_repo._dirty_relpaths() == frozenset()

    def test_nested_path(self, git_repo: DotRepository) -> None:
        nested = git_repo.path / ".config" / "nvim"
        nested.mkdir(parents=True)
        (nested / "init.vim").write_text("set number")

        assert ".config/nvim/init.vim" in git_repo._dirty_relpaths()


class TestSyncCommitsDirty:
    def test_dirty_file_committed_after_sync(self, git_repo: DotRepository, fake_home: Path) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        # create correct symlink so sync sees OK status
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)
        # now dirty the file
        repo_file.write_text("modified outside dots")

        git_repo.sync()

        assert not git_repo.git.is_dirty(untracked_files=True)

    def test_untracked_file_committed_after_sync(self, git_repo: DotRepository, fake_home: Path) -> None:
        repo_file = git_repo.path / "vimrc"
        repo_file.write_text("set number")

        git_repo.sync()

        assert git_repo.git is not None
        assert not git_repo.git.is_dirty(untracked_files=True)

    def test_dirty_not_committed_in_list_mode(self, git_repo: DotRepository, fake_home: Path) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)
        repo_file.write_text("modified")

        git_repo.sync(list_only=True)

        assert git_repo.git.is_dirty()

    def test_commit_message_format(self, git_repo: DotRepository, fake_home: Path) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)
        repo_file.write_text("changed")

        git_repo.sync()

        last_msg = git_repo.git.head.commit.message.strip()
        assert last_msg == "[dots] sync bashrc"


class TestSyncShowsCommitted:
    def test_sync_shows_committed(
        self, git_repo: DotRepository, fake_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)
        repo_file.write_text("dirty")

        git_repo.sync()

        captured = capsys.readouterr()
        assert "committed" in captured.out
        assert "uncommitted" not in captured.out


class TestListShowsDirty:
    def test_ok_file_shows_dirty(
        self, git_repo: DotRepository, fake_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("original")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)
        repo_file.write_text("dirty")

        git_repo.sync(list_only=True)

        captured = capsys.readouterr()
        assert "uncommitted" in captured.out

    def test_clean_file_no_tag(
        self, git_repo: DotRepository, fake_home: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo_file = git_repo.path / "bashrc"
        repo_file.write_text("clean")
        assert git_repo.git is not None
        git_repo.git.index.add(["bashrc"])
        git_repo.git.index.commit("[dots] added bashrc")
        link = fake_home / "bashrc"
        link.symlink_to(repo_file)

        git_repo.sync(list_only=True)

        captured = capsys.readouterr()
        assert "uncommitted" not in captured.out
