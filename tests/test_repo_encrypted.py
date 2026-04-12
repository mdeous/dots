from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dots import crypto
from dots.crypto import AgeKeyPair, age_encrypt
from dots.errors import CryptoError, FsError
from dots.repo import DotRepository, SyncOutcome

from .conftest import StubUI

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _setup_encrypted_file(
    fake_home: Path,
    fake_repo: Path,
    age_keypair: AgeKeyPair,
    relpath: str,
    content: bytes = b"secret data",
) -> tuple[Path, Path, Path]:
    """
    Manually set up an encrypted file in the repo as if ``add --encrypt``
    had already run.  Returns ``(home_file, age_file, decrypted_file)``.
    """
    age_file = fake_repo / (relpath + crypto.AGE_EXTENSION)
    decrypted_dir = fake_repo / crypto.DECRYPTED_DIR
    decrypted_file = decrypted_dir / relpath

    ciphertext = age_encrypt(content, age_keypair.recipient)
    age_file.parent.mkdir(parents=True, exist_ok=True)
    age_file.write_bytes(ciphertext)

    decrypted_file.parent.mkdir(parents=True, exist_ok=True)
    decrypted_file.write_bytes(content)

    home_file = fake_home / relpath
    home_file.parent.mkdir(parents=True, exist_ok=True)
    home_file.symlink_to(decrypted_file)

    # ensure .gitignore
    gitignore = fake_repo / ".gitignore"
    marker = f"/{crypto.DECRYPTED_DIR}/"
    if not gitignore.is_file() or marker not in gitignore.read_text():
        gitignore.write_text(f"{marker}\n")

    return home_file, age_file, decrypted_file


# ---------------------------------------------------------------------------
# add --encrypt
# ---------------------------------------------------------------------------


class TestAddEncrypted:
    def test_creates_age_file_and_symlink(
        self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path, age_keypair: AgeKeyPair
    ) -> None:
        target = fake_home / ".secret.conf"
        target.write_bytes(b"api_key=12345")

        dot_repo_encrypted.add(target, encrypt=True)

        age_file = fake_repo / ".secret.conf.age"
        assert age_file.exists()
        decrypted = fake_repo / ".decrypted" / ".secret.conf"
        assert decrypted.exists()
        assert decrypted.read_bytes() == b"api_key=12345"
        assert target.is_symlink()
        assert target.resolve() == decrypted.resolve()
        assert target.read_bytes() == b"api_key=12345"

    def test_age_file_is_valid_ciphertext(
        self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path, age_keypair: AgeKeyPair
    ) -> None:
        target = fake_home / "secret.txt"
        target.write_bytes(b"classified")

        dot_repo_encrypted.add(target, encrypt=True)

        age_file = fake_repo / "secret.txt.age"
        decrypted = crypto.age_decrypt(age_file.read_bytes(), age_keypair.identity)
        assert decrypted == b"classified"

    def test_nested_path(self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        nested = fake_home / ".config" / "app"
        nested.mkdir(parents=True)
        target = nested / "secrets.env"
        target.write_bytes(b"DB_PASS=hunter2")

        dot_repo_encrypted.add(target, encrypt=True)

        assert (fake_repo / ".config" / "app" / "secrets.env.age").exists()
        assert (fake_repo / ".decrypted" / ".config" / "app" / "secrets.env").exists()

    def test_gitignore_created(self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        target = fake_home / "secret.txt"
        target.write_bytes(b"data")

        dot_repo_encrypted.add(target, encrypt=True)

        gitignore = fake_repo / ".gitignore"
        assert gitignore.exists()
        assert f"/{crypto.DECRYPTED_DIR}/" in gitignore.read_text()

    def test_gitignore_idempotent(self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        (fake_repo / ".gitignore").write_text(f"/{crypto.DECRYPTED_DIR}/\n")
        target = fake_home / "secret.txt"
        target.write_bytes(b"data")

        dot_repo_encrypted.add(target, encrypt=True)

        content = (fake_repo / ".gitignore").read_text()
        assert content.count(f"/{crypto.DECRYPTED_DIR}/") == 1

    def test_gitignore_appends_to_existing(
        self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path
    ) -> None:
        (fake_repo / ".gitignore").write_text("*.swp\n")
        target = fake_home / "secret.txt"
        target.write_bytes(b"data")

        dot_repo_encrypted.add(target, encrypt=True)

        content = (fake_repo / ".gitignore").read_text()
        assert "*.swp" in content
        assert f"/{crypto.DECRYPTED_DIR}/" in content

    def test_no_age_key_raises(self, dot_repo: DotRepository, fake_home: Path) -> None:
        target = fake_home / "secret.txt"
        target.write_bytes(b"data")

        with pytest.raises(CryptoError, match="no age identity configured"):
            dot_repo.add(target, encrypt=True)

    def test_rollback_on_symlink_failure(
        self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path
    ) -> None:
        target = fake_home / "secret.txt"
        target.write_bytes(b"precious secret")

        from unittest.mock import patch

        with patch("dots.fs.atomic_symlink", side_effect=FsError("fail", target)), pytest.raises(FsError):
            dot_repo_encrypted.add(target, encrypt=True)

        assert target.read_bytes() == b"precious secret"
        assert not target.is_symlink()
        assert not (fake_repo / "secret.txt.age").exists()
        assert not (fake_repo / ".decrypted" / "secret.txt").exists()

    def test_plain_add_still_works(self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        target = fake_home / "normal.conf"
        target.write_text("not secret")

        dot_repo_encrypted.add(target)

        assert (fake_repo / "normal.conf").exists()
        assert target.is_symlink()
        assert target.resolve() == (fake_repo / "normal.conf").resolve()

    def test_empty_file(self, dot_repo_encrypted: DotRepository, fake_home: Path, fake_repo: Path) -> None:
        target = fake_home / "empty.txt"
        target.write_bytes(b"")

        dot_repo_encrypted.add(target, encrypt=True)

        decrypted = fake_repo / ".decrypted" / "empty.txt"
        assert decrypted.read_bytes() == b""
        assert target.is_symlink()


# ---------------------------------------------------------------------------
# sync -- encrypted files
# ---------------------------------------------------------------------------


class TestSyncEncrypted:
    def test_first_sync_decrypts_and_symlinks(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        """Simulate cloning to a new machine: .age file exists, no decrypted copy."""
        age_file = fake_repo / "secret.conf.age"
        ciphertext = age_encrypt(b"new machine data", age_keypair.recipient)
        age_file.write_bytes(ciphertext)

        repo = DotRepository(path=fake_repo, home=fake_home, ignored=(), git=None, ui=stub_ui, age_keypair=age_keypair)
        repo.sync()

        decrypted = fake_repo / ".decrypted" / "secret.conf"
        assert decrypted.exists()
        assert decrypted.read_bytes() == b"new machine data"
        home_file = fake_home / "secret.conf"
        assert home_file.is_symlink()
        assert home_file.resolve() == decrypted.resolve()

    def test_unchanged_file_stays_ok(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"unchanged")

        dot_repo_encrypted.sync()

        # age file should not have changed (no re-encryption)
        age_file = fake_repo / "secret.txt.age"
        original_ciphertext = age_file.read_bytes()
        dot_repo_encrypted.sync()
        assert age_file.read_bytes() == original_ciphertext

    def test_modified_file_re_encrypts(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        _, age_file, decrypted_file = _setup_encrypted_file(
            fake_home, fake_repo, age_keypair, "secret.txt", b"original"
        )
        original_ciphertext = age_file.read_bytes()

        # user modifies the file through the symlink
        decrypted_file.write_bytes(b"modified by user")

        dot_repo_encrypted.sync()

        # .age file should have been re-encrypted
        new_ciphertext = age_file.read_bytes()
        assert new_ciphertext != original_ciphertext
        # verify the re-encrypted content is correct
        decrypted = crypto.age_decrypt(new_ciphertext, age_keypair.identity)
        assert decrypted == b"modified by user"

    def test_broken_symlink_repaired(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        home_file, _, decrypted_file = _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"data")
        # break the symlink
        home_file.unlink()

        dot_repo_encrypted.sync()

        assert home_file.is_symlink()
        assert home_file.resolve() == decrypted_file.resolve()

    def test_missing_key_skips_with_warning(
        self,
        dot_repo: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        """dot_repo has no age_keypair (None). Encrypted files should be skipped."""
        ciphertext = age_encrypt(b"data", age_keypair.recipient)
        (fake_repo / "secret.age").write_bytes(ciphertext)

        dot_repo.sync()  # should not raise

        assert not (fake_home / "secret").exists()

    def test_list_only_shows_encrypted_files(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"data")

        dot_repo_encrypted.sync(list_only=True)

        # file should not have been modified
        home_file = fake_home / "secret.txt"
        assert home_file.is_symlink()

    def test_list_only_missing_decrypted(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        """list_only should report missing without creating decrypted copy."""
        ciphertext = age_encrypt(b"data", age_keypair.recipient)
        (fake_repo / "secret.age").write_bytes(ciphertext)

        repo = DotRepository(path=fake_repo, home=fake_home, ignored=(), git=None, ui=stub_ui, age_keypair=age_keypair)
        repo.sync(list_only=True)

        assert not (fake_repo / ".decrypted" / "secret").exists()
        assert not (fake_home / "secret").exists()

    def test_mixed_plain_and_encrypted(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        # regular file
        (fake_repo / "bashrc").write_text("alias ls='ls --color'")
        # encrypted file
        ciphertext = age_encrypt(b"secret", age_keypair.recipient)
        (fake_repo / "secret.conf.age").write_bytes(ciphertext)

        dot_repo_encrypted.sync()

        assert (fake_home / "bashrc").is_symlink()
        assert (fake_home / "bashrc").read_text() == "alias ls='ls --color'"
        assert (fake_home / "secret.conf").is_symlink()
        assert (fake_home / "secret.conf").read_bytes() == b"secret"

    def test_sync_outcome_replaced_on_reencrypt(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        _, _, decrypted_file = _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"original")
        decrypted_file.write_bytes(b"modified")

        repo = DotRepository(path=fake_repo, home=fake_home, ignored=(), git=None, ui=stub_ui, age_keypair=age_keypair)
        result = repo.sync_one_encrypted(
            repo_file=fake_repo / "secret.txt.age",
            list_only=False,
        )
        assert result == SyncOutcome.REPLACED

    def test_nested_encrypted_sync(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        nested = fake_repo / ".config" / "app"
        nested.mkdir(parents=True)
        ciphertext = age_encrypt(b"nested secret", age_keypair.recipient)
        (nested / "creds.age").write_bytes(ciphertext)

        dot_repo_encrypted.sync()

        home_file = fake_home / ".config" / "app" / "creds"
        assert home_file.is_symlink()
        assert home_file.read_bytes() == b"nested secret"
        decrypted = fake_repo / ".decrypted" / ".config" / "app" / "creds"
        assert decrypted.exists()


# ---------------------------------------------------------------------------
# remove -- encrypted files
# ---------------------------------------------------------------------------


class TestRemoveEncrypted:
    def test_restores_decrypted_content(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        home_file, age_file, decrypted_file = _setup_encrypted_file(
            fake_home, fake_repo, age_keypair, "secret.txt", b"restored content"
        )

        dot_repo_encrypted.remove(home_file)

        assert not home_file.is_symlink()
        assert home_file.is_file()
        assert home_file.read_bytes() == b"restored content"
        assert not age_file.exists()
        assert not decrypted_file.exists()

    def test_cleans_empty_parent_dirs(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        home_file, _, _ = _setup_encrypted_file(fake_home, fake_repo, age_keypair, ".config/app/secret.key", b"data")

        dot_repo_encrypted.remove(home_file)

        assert not (fake_repo / ".config" / "app").exists()
        assert not (fake_repo / ".decrypted" / ".config" / "app").exists()

    def test_preserves_nonempty_parent_dirs(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        home_file, _, _ = _setup_encrypted_file(fake_home, fake_repo, age_keypair, ".config/secret.key", b"data")
        (fake_repo / ".config" / "other.conf").write_text("keep")

        dot_repo_encrypted.remove(home_file)

        assert (fake_repo / ".config").is_dir()
        assert (fake_repo / ".config" / "other.conf").exists()

    def test_regular_remove_still_works(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
    ) -> None:
        repo_file = fake_repo / "normal.conf"
        repo_file.write_text("config data")
        home_file = fake_home / "normal.conf"
        home_file.symlink_to(repo_file)

        dot_repo_encrypted.remove(home_file)

        assert not home_file.is_symlink()
        assert home_file.read_text() == "config data"
        assert not repo_file.exists()


# ---------------------------------------------------------------------------
# iter_repo_files -- .decrypted skipping
# ---------------------------------------------------------------------------


class TestIterRepoFilesEncrypted:
    def test_skips_decrypted_directory(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        (fake_repo / "normal.txt").write_text("a")
        (fake_repo / "secret.age").write_bytes(b"encrypted")
        decrypted_dir = fake_repo / ".decrypted"
        decrypted_dir.mkdir()
        (decrypted_dir / "secret").write_text("plaintext")

        files = list(dot_repo_encrypted.iter_repo_files())
        relpaths = {f.relative_to(fake_repo).as_posix() for f in files}

        assert "normal.txt" in relpaths
        assert "secret.age" in relpaths
        assert ".decrypted/secret" not in relpaths

    def test_age_files_are_yielded(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        (fake_repo / ".config" / "app.conf.age").parent.mkdir(parents=True)
        (fake_repo / ".config" / "app.conf.age").write_bytes(b"data")

        files = list(dot_repo_encrypted.iter_repo_files())
        relpaths = {f.relative_to(fake_repo).as_posix() for f in files}

        assert ".config/app.conf.age" in relpaths


# ---------------------------------------------------------------------------
# ensure_decrypted_gitignored
# ---------------------------------------------------------------------------


class TestEnsureDecryptedGitignored:
    def test_creates_gitignore(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        dot_repo_encrypted.ensure_decrypted_gitignored()

        gitignore = fake_repo / ".gitignore"
        assert gitignore.exists()
        assert f"/{crypto.DECRYPTED_DIR}/" in gitignore.read_text()

    def test_appends_to_existing(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        (fake_repo / ".gitignore").write_text("*.swp\n")

        dot_repo_encrypted.ensure_decrypted_gitignored()

        content = (fake_repo / ".gitignore").read_text()
        assert "*.swp" in content
        assert f"/{crypto.DECRYPTED_DIR}/" in content

    def test_idempotent(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        dot_repo_encrypted.ensure_decrypted_gitignored()
        dot_repo_encrypted.ensure_decrypted_gitignored()

        content = (fake_repo / ".gitignore").read_text()
        assert content.count(f"/{crypto.DECRYPTED_DIR}/") == 1

    def test_appends_missing_newline(self, dot_repo_encrypted: DotRepository, fake_repo: Path) -> None:
        (fake_repo / ".gitignore").write_text("*.swp")  # no trailing newline

        dot_repo_encrypted.ensure_decrypted_gitignored()

        content = (fake_repo / ".gitignore").read_text()
        assert "*.swp\n" in content


# ---------------------------------------------------------------------------
# git integration with encrypted files
# ---------------------------------------------------------------------------


class TestGitCommitEncrypted:
    def test_commit_called_on_add_encrypted(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        mock_git = MagicMock()
        repo = DotRepository(
            path=fake_repo, home=fake_home, ignored=(), git=mock_git, ui=stub_ui, age_keypair=age_keypair
        )

        target = fake_home / "secret.txt"
        target.write_bytes(b"data")
        repo.add(target, encrypt=True)

        mock_git.git.add.assert_called_with(all=True)
        call_msg = mock_git.git.commit.call_args[1]["message"]
        assert "encrypted" in call_msg
        assert "secret.txt" in call_msg

    def test_commit_on_reencrypt(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        _, _, decrypted_file = _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"original")
        decrypted_file.write_bytes(b"modified")

        mock_git = MagicMock()
        repo = DotRepository(
            path=fake_repo, home=fake_home, ignored=(), git=mock_git, ui=stub_ui, age_keypair=age_keypair
        )
        repo.sync()

        call_msg = mock_git.git.commit.call_args[1]["message"]
        assert "re-encrypted" in call_msg

    def test_commit_on_remove_encrypted(
        self,
        fake_home: Path,
        fake_repo: Path,
        stub_ui: StubUI,
        age_keypair: AgeKeyPair,
    ) -> None:
        home_file, _, _ = _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"data")

        mock_git = MagicMock()
        repo = DotRepository(
            path=fake_repo, home=fake_home, ignored=(), git=mock_git, ui=stub_ui, age_keypair=age_keypair
        )
        repo.remove(home_file)

        call_msg = mock_git.git.commit.call_args[1]["message"]
        assert "removed" in call_msg
        assert "encrypted" in call_msg


# ---------------------------------------------------------------------------
# validate_addable with encrypted files
# ---------------------------------------------------------------------------


class TestValidateAddableEncrypted:
    def test_already_tracked_encrypted_symlink(
        self,
        dot_repo_encrypted: DotRepository,
        fake_home: Path,
        fake_repo: Path,
        age_keypair: AgeKeyPair,
    ) -> None:
        """A symlink pointing into .decrypted/ should be detected as already tracked."""
        home_file, _, _ = _setup_encrypted_file(fake_home, fake_repo, age_keypair, "secret.txt", b"data")

        from dots.errors import AlreadyInRepoError

        with pytest.raises(AlreadyInRepoError):
            dot_repo_encrypted.add(home_file)
