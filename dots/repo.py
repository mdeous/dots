from __future__ import annotations

import contextlib
import enum
import fnmatch
import platform
from collections.abc import Iterator
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path

from git import Repo as GitRepo
from git.exc import GitError

from dots import crypto, fs
from dots.crypto import AgeKeyPair
from dots.errors import (
    AlreadyEncryptedError,
    AlreadyInRepoError,
    ConfigError,
    CryptoError,
    DotsError,
    InvalidTargetError,
    NotInHomeError,
    NotInRepoError,
    RepoError,
)
from dots.ui import UI


class SyncOutcome(enum.Enum):
    OK = "ok"
    INSTALLED = "installed"
    REPLACED = "replaced"
    MISSING = "missing"
    CONFLICT = "conflict"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class DotConfig:
    repo_dir: Path
    ignored: tuple[str, ...]
    age_identity: Path | None


def load_config(config_path: Path) -> DotConfig:
    """
    Parse the config file and return a ``DotConfig``.

    Selects a hostname-specific section if one is present, otherwise falls back
    to ``[DEFAULT]``. Uses defaults if file is missing.
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

    raw_age_identity = section.get("age_identity", "")
    age_identity: Path | None = None
    if raw_age_identity.strip():
        age_identity = Path(raw_age_identity.strip()).expanduser().resolve()

    return DotConfig(repo_dir=repo_dir, ignored=ignored, age_identity=age_identity)


@dataclass(frozen=True)
class DotRepository:
    """
    A dotfiles repository.
    """

    path: Path
    home: Path
    ignored: tuple[str, ...]
    git: GitRepo | None
    ui: UI
    age_keypair: AgeKeyPair | None = None

    @classmethod
    def load(cls, config_path: Path, ui: UI) -> DotRepository:
        ui.debug(f"Loading configuration from {config_path}")
        config = load_config(config_path)
        if not config.repo_dir.is_dir():
            raise RepoError(f"no dots repository found at {config.repo_dir}")

        git_repo: GitRepo | None = None
        if (config.repo_dir / ".git").is_dir():
            try:
                git_repo = GitRepo(config.repo_dir)
            except GitError as e:
                ui.warning(f"could not open git repo at {config.repo_dir}: {e}")

        age_keypair: AgeKeyPair | None = None
        if config.age_identity is not None:
            try:
                age_keypair = crypto.load_identity(config.age_identity)
            except CryptoError as e:
                ui.warning(f"age identity unavailable: {e}")

        return cls(
            path=config.repo_dir,
            home=Path.home().resolve(),
            ignored=config.ignored,
            git=git_repo,
            ui=ui,
            age_keypair=age_keypair,
        )

    def add(self, target: Path, *, encrypt: bool = False) -> None:
        """
        Move ``target`` into the repository and replace it with a symlink.

        When ``encrypt`` is True the file is stored as an age-encrypted
        ``.age`` file and a decrypted working copy in ``.decrypted/`` is
        used as the symlink target.

        If ``encrypt`` is True and the file is already tracked as plaintext,
        it is converted to encrypted tracking after user confirmation.

        Safety: the file is copied into the repo first, then the symlink is
        installed atomically. If the symlink step fails the stray copy is
        removed - the user's file is never in an unreachable state.
        """
        target = target.absolute()
        self.ui.debug(f"Adding '{target}' to the repository...")

        if encrypt:
            repo_file = self._tracked_plain_file(target)
            if repo_file is not None:
                if not self.ui.ask_yesno(f"Encrypt already tracked file '{target.name}'?", default=False):
                    return
                self._convert_plain_to_encrypted(target, repo_file)
                return
            if self._tracked_encrypted_file(target):
                raise AlreadyEncryptedError(target)

        self.validate_addable(target)

        if encrypt:
            self._add_encrypted(target)
        else:
            self._add_plain(target)

    def _add_plain(self, target: Path) -> None:
        relpath = target.relative_to(self.home)
        repo_file = self.path / relpath

        self.ui.debug(f"Copying {target} to {repo_file}")
        fs.atomic_copy(target, repo_file)

        try:
            self.ui.debug(f"Creating symlink at {target}")
            fs.atomic_symlink(repo_file, target)
        except DotsError:
            with contextlib.suppress(DotsError):
                fs.safe_unlink(repo_file)
            raise

        self.git_commit_safe(f"added {relpath.as_posix()}")
        self.ui.installed(target)

    def _add_encrypted(self, target: Path) -> None:
        if self.age_keypair is None:
            raise CryptoError("no age identity configured")

        relpath = target.relative_to(self.home)
        age_file = crypto.home_to_age_path(self.path, self.home, target)
        decrypted_path = crypto.age_to_decrypted_path(self.path, age_file)

        plaintext = target.read_bytes()
        ciphertext = crypto.age_encrypt(plaintext, self.age_keypair.recipient)

        self.ui.debug(f"Encrypting {target} to {age_file}")
        fs.atomic_write(age_file, ciphertext)

        self.ui.debug(f"Writing decrypted copy to {decrypted_path}")
        fs.atomic_write(decrypted_path, plaintext)

        self.ensure_decrypted_gitignored()

        try:
            self.ui.debug(f"Creating symlink at {target}")
            fs.atomic_symlink(decrypted_path, target)
        except DotsError:
            with contextlib.suppress(DotsError):
                fs.safe_unlink(age_file)
            with contextlib.suppress(DotsError):
                fs.safe_unlink(decrypted_path)
            raise

        self.git_commit_safe(f"added {relpath.as_posix()} (encrypted)")
        self.ui.installed(target, encrypted=True)

    def _tracked_plain_file(self, target: Path) -> Path | None:
        """
        If *target* is a symlink pointing to a plaintext repo file, return
        the resolved repo path.  Otherwise return ``None``.
        """
        if not target.is_symlink():
            return None
        resolved = target.resolve()
        if not fs.is_inside(resolved, self.path):
            return None
        decrypted_dir = self.path / crypto.DECRYPTED_DIR
        if fs.is_inside(resolved, decrypted_dir):
            return None
        return resolved

    def _tracked_encrypted_file(self, target: Path) -> bool:
        """Return ``True`` if *target* is tracked as an encrypted file."""
        if not target.is_symlink():
            return False
        resolved = target.resolve()
        if not fs.is_inside(resolved, self.path):
            return False
        decrypted_dir = self.path / crypto.DECRYPTED_DIR
        return fs.is_inside(resolved, decrypted_dir)

    def _convert_plain_to_encrypted(self, target: Path, repo_file: Path) -> None:
        """
        Convert an already-tracked plaintext file to encrypted tracking.

        Safety: at every step the user's data is reachable through at least
        one path (the original repo file, the new ``.age`` file, or the
        ``.decrypted`` copy).  The old plaintext repo file is deleted last.
        """
        if self.age_keypair is None:
            raise CryptoError("no age identity configured")

        relpath = target.relative_to(self.home)
        age_file = crypto.home_to_age_path(self.path, self.home, target)
        decrypted_path = crypto.age_to_decrypted_path(self.path, age_file)

        plaintext = repo_file.read_bytes()
        ciphertext = crypto.age_encrypt(plaintext, self.age_keypair.recipient)

        self.ui.debug(f"Encrypting {target} to {age_file}")
        fs.atomic_write(age_file, ciphertext)

        self.ui.debug(f"Writing decrypted copy to {decrypted_path}")
        fs.atomic_write(decrypted_path, plaintext)

        self.ensure_decrypted_gitignored()

        try:
            self.ui.debug(f"Repointing symlink at {target}")
            fs.atomic_symlink(decrypted_path, target)
        except DotsError:
            with contextlib.suppress(DotsError):
                fs.safe_unlink(age_file)
            with contextlib.suppress(DotsError):
                fs.safe_unlink(decrypted_path)
            raise

        self.ui.debug(f"Removing old plaintext repo file {repo_file}")
        fs.safe_unlink(repo_file)
        self.rm_empty_folders(repo_file.parent)

        self.git_commit_safe(f"encrypted {relpath.as_posix()}")
        self.ui.installed(target, encrypted=True)

    def remove(self, target: Path) -> None:
        """
        Restore a repository file to its original location and un-track it.

        Safety: the repo content is copied back to the home location first (an
        atomic ``os.replace`` that swaps the symlink for a regular file). Only
        after that commit step is the repo copy deleted.
        """
        target = target.absolute()
        self.ui.debug(f"Removing '{target}' from the repository...")

        repo_file = target.resolve()
        if not fs.is_inside(repo_file, self.path):
            raise NotInRepoError(target)

        # detect encrypted files: symlink target is inside .decrypted/
        decrypted_dir = self.path / crypto.DECRYPTED_DIR
        if fs.is_inside(repo_file, decrypted_dir):
            self._remove_encrypted(target, repo_file)
            return

        relpath = repo_file.relative_to(self.path)
        home_file = self.home / relpath

        if not home_file.is_symlink():
            raise InvalidTargetError(f"expected symlink at {home_file}", home_file)
        if home_file.resolve() != repo_file:
            raise InvalidTargetError(f"{home_file} does not point to {repo_file}", home_file)

        # install a regular-file copy at home_file (atomically replaces the symlink)
        self.ui.debug(f"Restoring {repo_file} to {home_file}")
        fs.atomic_copy(repo_file, home_file)

        # drop the repo-side copy
        self.ui.debug(f"Removing repo file {repo_file}")
        fs.safe_unlink(repo_file)

        # clean empty parent dirs in the repo
        self.rm_empty_folders(repo_file.parent)

        # commit to git
        self.git_commit_safe(f"removed {relpath.as_posix()}")
        self.ui.removed(target)

    def _remove_encrypted(self, target: Path, decrypted_file: Path) -> None:
        decrypted_dir = self.path / crypto.DECRYPTED_DIR
        rel_in_decrypted = decrypted_file.relative_to(decrypted_dir)
        age_file = self.path / (rel_in_decrypted.as_posix() + crypto.AGE_EXTENSION)
        home_file = self.home / rel_in_decrypted

        if not home_file.is_symlink():
            raise InvalidTargetError(f"expected symlink at {home_file}", home_file)
        if home_file.resolve() != decrypted_file:
            raise InvalidTargetError(f"{home_file} does not point to {decrypted_file}", home_file)

        # restore decrypted content to home location
        self.ui.debug(f"Restoring {decrypted_file} to {home_file}")
        fs.atomic_copy(decrypted_file, home_file)

        # remove .age file and decrypted copy
        self.ui.debug(f"Removing {age_file}")
        fs.safe_unlink(age_file)
        self.ui.debug(f"Removing {decrypted_file}")
        fs.safe_unlink(decrypted_file)

        # clean empty dirs in both repo and .decrypted
        self.rm_empty_folders(age_file.parent)
        self.rm_empty_folders(decrypted_file.parent)

        self.git_commit_safe(f"removed {rel_in_decrypted.as_posix()} (encrypted)")
        self.ui.removed(target, encrypted=True)

    def sync(
        self,
        *,
        list_only: bool = False,
        force_relink: bool = False,
        force_add: bool = False,
        force_link: bool = False,
    ) -> None:
        if not list_only:
            self.ui.section("Syncing dotfiles", emoji="📦")
        else:
            self.ui.section("Listing dotfiles", emoji="📦")

        changed = 0
        unchanged = 0
        dirty = self._dirty_relpaths()

        for repo_file in self.iter_repo_files():
            relpath = repo_file.relative_to(self.path)
            if self.is_ignored(relpath):
                self.ui.debug(f"Ignored: {relpath.as_posix()}")
                continue

            is_dirty = relpath.as_posix() in dirty
            show_dirty = is_dirty and list_only

            if crypto.is_age_file(repo_file):
                outcome = self.sync_one_encrypted(
                    repo_file=repo_file,
                    list_only=list_only,
                    dirty=show_dirty,
                )
            else:
                link_path = self.home / relpath
                outcome = self.sync_one(
                    repo_file=repo_file,
                    link_path=link_path,
                    list_only=list_only,
                    force_relink=force_relink,
                    force_add=force_add,
                    force_link=force_link,
                    dirty=show_dirty,
                )

            if not list_only and is_dirty and self._git_commit_path(relpath.as_posix(), f"sync {relpath.as_posix()}"):
                self.ui.committed(relpath)

            if outcome == SyncOutcome.OK:
                unchanged += 1
            elif outcome in (SyncOutcome.INSTALLED, SyncOutcome.REPLACED):
                changed += 1

        self.ui.summary(changed=changed, unchanged=unchanged)

    def validate_addable(self, target: Path) -> None:
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
            raise InvalidTargetError(f"file is already inside the repository: {target}", target)

    def iter_repo_files(self) -> Iterator[Path]:
        """
        Yield every regular file under ``self.path``, skipping ``.git``
        and ``.decrypted``.
        """
        for p in sorted(self.path.rglob("*")):
            if not p.is_file():
                continue
            parts = p.relative_to(self.path).parts
            if ".git" in parts:
                continue
            if parts[0] == crypto.DECRYPTED_DIR:
                continue
            yield p

    def is_ignored(self, relpath: Path) -> bool:
        """
        Match ``relpath`` (repo-relative) against the ignore patterns.

        Patterns starting with ``/`` are anchored to the repo root and match
        the full relative path. All other patterns match the filename only.
        """
        rel_str = "/" + relpath.as_posix()
        for pattern in self.ignored:
            match_target = rel_str if pattern.startswith("/") else relpath.name
            if fnmatch.fnmatch(match_target, pattern):
                return True
        return False

    def sync_one(
        self,
        *,
        repo_file: Path,
        link_path: Path,
        list_only: bool,
        force_relink: bool,
        force_add: bool,
        force_link: bool,
        dirty: bool = False,
    ) -> SyncOutcome:
        if not (link_path.is_symlink() or link_path.exists()):
            if list_only:
                self.ui.missing(link_path, dirty=dirty)
                return SyncOutcome.MISSING
            fs.atomic_symlink(repo_file, link_path)
            self.ui.installed(link_path, dirty=dirty)
            return SyncOutcome.INSTALLED

        if link_path.is_symlink():
            link_target = link_path.resolve()
            if link_target == repo_file:
                self.ui.ok(link_path, dirty=dirty)
                return SyncOutcome.OK
            state = "valid" if link_target.exists() else "broken"
            self.ui.conflict(link_path, target=link_target, reason=f"{state} link", dirty=dirty)
            if list_only:
                return SyncOutcome.CONFLICT
            if not force_relink and not self.ui.ask_yesno("Overwrite existing link?", default=False):
                return SyncOutcome.SKIPPED
            fs.atomic_symlink(repo_file, link_path)
            self.ui.replaced(link_path, dirty=dirty)
            return SyncOutcome.REPLACED

        self.ui.conflict(link_path, reason="file exists", dirty=dirty)
        if list_only:
            return SyncOutcome.CONFLICT
        if force_add:
            self.force_add(repo_file, link_path)
            return SyncOutcome.REPLACED
        if force_link:
            self.force_link(repo_file, link_path)
            return SyncOutcome.REPLACED
        if self.ui.ask_yesno("Replace repository file?", default=False):
            self.force_add(repo_file, link_path)
            return SyncOutcome.REPLACED
        if self.ui.ask_yesno("Replace local file?", default=False):
            self.force_link(repo_file, link_path)
            return SyncOutcome.REPLACED
        return SyncOutcome.SKIPPED

    def force_add(self, repo_file: Path, link_path: Path) -> None:
        """
        Promote the user's local file to become the new repo version.
        """
        self.ui.debug(f"Force-add: {link_path} -> {repo_file}")
        fs.atomic_copy(link_path, repo_file)
        fs.atomic_symlink(repo_file, link_path)
        self.git_commit_safe(f"force-updated {repo_file.relative_to(self.path).as_posix()}")
        self.ui.replaced(repo_file)

    def force_link(self, repo_file: Path, link_path: Path) -> None:
        """
        Replace the user's local file with a symlink pointing at the repo.
        """
        self.ui.debug(f"Force-link: {link_path} -> {repo_file}")
        fs.atomic_symlink(repo_file, link_path)
        self.ui.replaced(link_path)

    def sync_one_encrypted(
        self,
        *,
        repo_file: Path,
        list_only: bool,
        dirty: bool = False,
    ) -> SyncOutcome:
        if self.age_keypair is None:
            self.ui.warning(f"skipping encrypted file (no age key): {repo_file.name}")
            return SyncOutcome.SKIPPED

        decrypted_path = crypto.age_to_decrypted_path(self.path, repo_file)
        home_path = crypto.age_to_home_path(self.path, self.home, repo_file)

        if not decrypted_path.exists():
            if list_only:
                self.ui.missing(home_path, encrypted=True, dirty=dirty)
                return SyncOutcome.MISSING
            ciphertext = repo_file.read_bytes()
            plaintext = crypto.age_decrypt(ciphertext, self.age_keypair.identity)
            fs.atomic_write(decrypted_path, plaintext)
            self.ensure_decrypted_gitignored()
            fs.atomic_symlink(decrypted_path, home_path)
            self.ui.installed(home_path, encrypted=True, dirty=dirty)
            return SyncOutcome.INSTALLED

        if not list_only:
            # integrity check: has the user modified the decrypted copy?
            ciphertext = repo_file.read_bytes()
            repo_plaintext = crypto.age_decrypt(ciphertext, self.age_keypair.identity)
            disk_plaintext = decrypted_path.read_bytes()

            if crypto.content_hash(repo_plaintext) != crypto.content_hash(disk_plaintext):
                new_ciphertext = crypto.age_encrypt(disk_plaintext, self.age_keypair.recipient)
                fs.atomic_write(repo_file, new_ciphertext)
                relpath = repo_file.relative_to(self.path)
                self.git_commit_safe(f"re-encrypted {relpath.as_posix()}")
                self.ui.replaced(home_path, encrypted=True, dirty=dirty)
                return SyncOutcome.REPLACED

        # ensure symlink is correct
        if home_path.is_symlink() and home_path.resolve() == decrypted_path.resolve():
            self.ui.ok(home_path, encrypted=True, dirty=dirty)
            return SyncOutcome.OK

        if list_only:
            self.ui.missing(home_path, encrypted=True, dirty=dirty)
            return SyncOutcome.MISSING

        self.ensure_decrypted_gitignored()
        fs.atomic_symlink(decrypted_path, home_path)
        self.ui.installed(home_path, encrypted=True, dirty=dirty)
        return SyncOutcome.INSTALLED

    def ensure_decrypted_gitignored(self) -> None:
        gitignore = self.path / ".gitignore"
        marker = f"/{crypto.DECRYPTED_DIR}/"
        if gitignore.is_file():
            content = gitignore.read_text()
            if marker in content:
                return
            if not content.endswith("\n"):
                content += "\n"
            content += f"{marker}\n"
        else:
            content = f"{marker}\n"
        fs.atomic_write(gitignore, content.encode())

    def rm_empty_folders(self, leaf: Path) -> None:
        """
        Iteratively delete empty directories up to ``self.path`` (exclusive).
        """
        while leaf != self.path and fs.is_inside(leaf, self.path):
            try:
                if any(leaf.iterdir()):
                    return
            except OSError:
                return
            if not self.ui.ask_yesno(f"Delete empty folder '{leaf}'?", default=True):
                return
            self.ui.debug(f"Deleting empty folder: {leaf}")
            try:
                leaf.rmdir()
            except OSError as e:
                self.ui.warning(f"Failed to delete {leaf}: {e}")
                return
            leaf = leaf.parent

    def git_commit_safe(self, msg: str) -> None:
        """
        Commit all repo changes - non-fatal on failure.
        """
        if self.git is None:
            return
        try:
            self.git.git.add(all=True)
            self.git.git.commit(message=f"[dots] {msg}")
        except GitError as e:
            self.ui.warning(f"git commit failed (filesystem change was applied): {e}")

    def _git_commit_path(self, relpath: str, msg: str) -> bool:
        if self.git is None:
            return False
        try:
            self.git.git.add("--", relpath)
            self.git.git.commit("--", relpath, message=f"[dots] {msg}")
            return True
        except GitError as e:
            if "nothing to commit" not in str(e):
                self.ui.warning(f"git commit failed (filesystem change was applied): {e}")
            return False

    def _dirty_relpaths(self) -> frozenset[str]:
        if self.git is None:
            return frozenset()
        output: str = self.git.git.status("--porcelain", untracked_files="all")
        if not output:
            return frozenset()
        paths: set[str] = set()
        for line in output.splitlines():
            path_part = line[3:]
            if " -> " in path_part:
                path_part = path_part.split(" -> ", 1)[1]
            paths.add(path_part)
        return frozenset(paths)
