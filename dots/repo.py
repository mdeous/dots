from __future__ import annotations

import contextlib
import fnmatch
import platform
from collections.abc import Iterator
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path

from git import Repo as GitRepo
from git.exc import GitError

from dots import fs
from dots.errors import (
    AlreadyInRepoError,
    ConfigError,
    DotsError,
    InvalidTargetError,
    NotInHomeError,
    NotInRepoError,
    RepoError,
)
from dots.ui import UI


def _load_config(config_path: Path) -> tuple[Path, tuple[str, ...]]:
    """Parse the config file and return ``(repo_dir, ignored_patterns)``.

    Selects a hostname-specific section if one is present, otherwise falls back
    to ``[DEFAULT]``. Missing config file is not an error — defaults apply.
    """
    cfg = ConfigParser(defaults={"repo_dir": "~/dots", "ignored_files": ""})
    if config_path.is_file():
        try:
            cfg.read(config_path)
        except ConfigParserError as e:
            raise ConfigError(f"invalid config file {config_path}: {e}") from e

    hostname = platform.node()
    section_name = hostname if hostname in cfg else "DEFAULT"
    section = cfg[section_name]

    repo_dir_raw = section.get("repo_dir")
    if not repo_dir_raw:
        raise ConfigError(f"missing 'repo_dir' in config section [{section_name}]")
    repo_dir = Path(repo_dir_raw).expanduser().resolve()

    raw_ignored = section.get("ignored_files", "")
    ignored = tuple(p.strip() for p in raw_ignored.split(",") if p.strip())

    return repo_dir, ignored


@dataclass(frozen=True)
class DotRepository:
    """A dotfiles repository: a directory whose contents are mirrored as symlinks in ``home``."""

    path: Path
    home: Path
    ignored: tuple[str, ...]
    git: GitRepo | None
    ui: UI

    @classmethod
    def load(cls, config_path: Path, ui: UI) -> DotRepository:
        ui.debug(f"Loading configuration from {config_path}")
        repo_dir, ignored = _load_config(config_path)
        if not repo_dir.is_dir():
            raise RepoError(f"no dots repository found at {repo_dir}")

        git_repo: GitRepo | None = None
        if (repo_dir / ".git").is_dir():
            try:
                git_repo = GitRepo(repo_dir)
            except GitError as e:
                ui.warning(f"could not open git repo at {repo_dir}: {e}")

        return cls(
            path=repo_dir,
            home=Path.home().resolve(),
            ignored=ignored,
            git=git_repo,
            ui=ui,
        )

    # ------------------------------------------------------------------
    # Public operations
    # ------------------------------------------------------------------

    def add(self, target: Path) -> None:
        """Move ``target`` into the repository and replace it with a symlink.

        Safety: the file is *copied* into the repo first, then the symlink is
        installed atomically. If the symlink step fails the stray copy is
        removed — the user's file is never in an unreachable state.
        """
        target = target.absolute()
        self.ui.debug(f"Adding '{target}' to the repository...")
        self._validate_addable(target)

        relpath = target.relative_to(self.home)
        repo_file = self.path / relpath

        # Step 1: stage a copy in the repo. target is still intact.
        self.ui.debug(f"Copying {target} to {repo_file}")
        fs.atomic_copy(target, repo_file)

        # Step 2: replace target with a symlink. Atomic; on failure, roll back.
        try:
            self.ui.debug(f"Creating symlink at {target}")
            fs.atomic_symlink(repo_file, target)
        except DotsError:
            with contextlib.suppress(DotsError):
                fs.safe_unlink(repo_file)
            raise

        # Step 3: commit to git. Non-fatal.
        self._git_commit_safe(f"added {relpath.as_posix()}")
        self.ui.info(f"File added: {target}")

    def remove(self, target: Path) -> None:
        """Restore a repository file to its original location and un-track it.

        Safety: the repo content is copied back to the home location first (an
        atomic ``os.replace`` that swaps the symlink for a regular file). Only
        after that commit step is the repo copy deleted.
        """
        target = target.absolute()
        self.ui.debug(f"Removing '{target}' from the repository...")

        repo_file = target.resolve()
        if not fs.is_inside(repo_file, self.path):
            raise NotInRepoError(target)

        relpath = repo_file.relative_to(self.path)
        home_file = self.home / relpath

        if not home_file.is_symlink():
            raise InvalidTargetError(f"expected symlink at {home_file}", home_file)
        if home_file.resolve() != repo_file:
            raise InvalidTargetError(
                f"{home_file} does not point to {repo_file}", home_file
            )

        # Step 1: install a regular-file copy at home_file (atomically replaces the symlink).
        self.ui.debug(f"Restoring {repo_file} to {home_file}")
        fs.atomic_copy(repo_file, home_file)

        # Step 2: drop the repo-side copy.
        self.ui.debug(f"Removing repo file {repo_file}")
        fs.safe_unlink(repo_file)

        # Step 3: clean empty parent dirs in the repo.
        self._rm_empty_folders(repo_file.parent)

        # Step 4: commit.
        self._git_commit_safe(f"removed {relpath.as_posix()}")
        self.ui.info(f"File removed: {target}")

    def sync(
        self,
        *,
        list_only: bool = False,
        force_relink: bool = False,
        force_add: bool = False,
        force_link: bool = False,
    ) -> None:
        """Reconcile every repo file against its expected symlink under ``home``."""
        if not list_only:
            self.ui.debug("Synchronizing repository files...")

        for repo_file in self._iter_repo_files():
            relpath = repo_file.relative_to(self.path)
            if self._is_ignored(relpath):
                self.ui.debug(f"Ignored: {relpath.as_posix()}")
                continue

            link_path = self.home / relpath
            self._sync_one(
                repo_file=repo_file,
                link_path=link_path,
                list_only=list_only,
                force_relink=force_relink,
                force_add=force_add,
                force_link=force_link,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _validate_addable(self, target: Path) -> None:
        if target.is_symlink():
            if fs.is_inside(target.resolve(), self.path):
                raise AlreadyInRepoError(target)
            raise InvalidTargetError(f"cannot add a symlink: {target}", target)
        if not target.exists():
            raise InvalidTargetError(f"file not found: {target}", target)
        if not target.is_file():
            raise InvalidTargetError(f"not a regular file: {target}", target)
        if not fs.is_inside(target, self.home):
            raise NotInHomeError(target, self.home)
        if fs.is_inside(target, self.path):
            raise InvalidTargetError(
                f"file is already inside the repository: {target}", target
            )

    def _iter_repo_files(self) -> Iterator[Path]:
        """Yield every regular file under ``self.path``, skipping ``.git``."""
        for p in sorted(self.path.rglob("*")):
            if not p.is_file():
                continue
            try:
                parts = p.relative_to(self.path).parts
            except ValueError:
                continue
            if ".git" in parts:
                continue
            yield p

    def _is_ignored(self, relpath: Path) -> bool:
        """Match ``relpath`` (repo-relative) against the ignore patterns.

        Patterns starting with ``/`` are anchored to the repo root and match
        the full relative path. All other patterns match the filename only.
        """
        rel_str = "/" + relpath.as_posix()
        for pattern in self.ignored:
            match_target = rel_str if pattern.startswith("/") else relpath.name
            if fnmatch.fnmatch(match_target, pattern):
                return True
        return False

    def _sync_one(
        self,
        *,
        repo_file: Path,
        link_path: Path,
        list_only: bool,
        force_relink: bool,
        force_add: bool,
        force_link: bool,
    ) -> None:
        # Truly missing at the home location (not even a broken symlink)?
        if not (link_path.is_symlink() or link_path.exists()):
            if list_only:
                self.ui.notice(f"Missing: {link_path}")
                return
            fs.atomic_symlink(repo_file, link_path)
            self.ui.info(f"Installed: {link_path}")
            return

        if link_path.is_symlink():
            link_target = link_path.resolve()
            if link_target == repo_file:
                self.ui.info(f"OK: {link_path}")
                return
            state = "valid" if link_target.exists() else "broken"
            self.ui.warning(
                f"Conflict ({state} link): {link_path} -> {link_target}"
            )
            if list_only:
                return
            if not force_relink and not self.ui.ask_yesno(
                "Overwrite existing link?", default=False
            ):
                return
            fs.atomic_symlink(repo_file, link_path)
            self.ui.info(f"Replaced link: {link_path}")
            return

        # link_path exists as a regular file
        self.ui.warning(f"Conflict (file exists): {link_path}")
        if list_only:
            return
        if force_add:
            self._force_add(repo_file, link_path)
        elif force_link:
            self._force_link(repo_file, link_path)
        elif self.ui.ask_yesno("Replace repository file?", default=False):
            self._force_add(repo_file, link_path)
        elif self.ui.ask_yesno("Replace local file?", default=False):
            self._force_link(repo_file, link_path)

    def _force_add(self, repo_file: Path, link_path: Path) -> None:
        """Promote the user's local file to become the new repo version."""
        self.ui.debug(f"Force-add: {link_path} -> {repo_file}")
        fs.atomic_copy(link_path, repo_file)
        fs.atomic_symlink(repo_file, link_path)
        self._git_commit_safe(
            f"force-updated {repo_file.relative_to(self.path).as_posix()}"
        )
        self.ui.info(f"Repository file replaced: {repo_file}")

    def _force_link(self, repo_file: Path, link_path: Path) -> None:
        """Replace the user's local file with a symlink pointing at the repo."""
        self.ui.debug(f"Force-link: {link_path} -> {repo_file}")
        fs.atomic_symlink(repo_file, link_path)
        self.ui.info(f"Local file replaced: {link_path}")

    def _rm_empty_folders(self, leaf: Path) -> None:
        """Iteratively delete empty directories up to ``self.path`` (exclusive)."""
        while leaf != self.path and fs.is_inside(leaf, self.path):
            try:
                if any(leaf.iterdir()):
                    return
            except OSError:
                return
            if not self.ui.ask_yesno(
                f"Delete empty folder '{leaf}'?", default=True
            ):
                return
            self.ui.debug(f"Deleting empty folder: {leaf}")
            try:
                leaf.rmdir()
            except OSError as e:
                self.ui.warning(f"Failed to delete {leaf}: {e}")
                return
            leaf = leaf.parent

    def _git_commit_safe(self, msg: str) -> None:
        """Commit all repo changes — non-fatal on failure (closes H8)."""
        if self.git is None:
            return
        try:
            self.git.git.add(all=True)
            self.git.git.commit(message=f"[dots] {msg}")
        except GitError as e:
            self.ui.warning(
                f"git commit failed (filesystem change was applied): {e}"
            )
