from __future__ import annotations

from pathlib import Path

import pytest
from pyrage import x25519

from dots.crypto import (
    AGE_EXTENSION,
    AgeKeyPair,
    age_decrypt,
    age_encrypt,
    age_to_decrypted_path,
    age_to_home_path,
    content_hash,
    home_to_age_path,
    is_age_file,
    load_identity,
)
from dots.errors import CryptoError


@pytest.fixture()
def age_keypair() -> AgeKeyPair:
    ident = x25519.Identity.generate()
    return AgeKeyPair(identity=ident, recipient=ident.to_public())


@pytest.fixture()
def age_identity_file(tmp_path: Path, age_keypair: AgeKeyPair) -> Path:
    key_file = tmp_path / "test.key"
    key_file.write_text(f"# created: 2024-01-01\n# public key: {age_keypair.recipient}\n{age_keypair.identity}\n")
    return key_file


class TestLoadIdentity:
    def test_valid_identity_file(self, age_identity_file: Path, age_keypair: AgeKeyPair) -> None:
        result = load_identity(age_identity_file)

        assert str(result.identity) == str(age_keypair.identity)
        assert str(result.recipient) == str(age_keypair.recipient)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CryptoError, match="cannot read identity file"):
            load_identity(tmp_path / "nonexistent.key")

    def test_empty_file_raises(self, tmp_path: Path) -> None:
        key_file = tmp_path / "empty.key"
        key_file.write_text("")

        with pytest.raises(CryptoError, match="no AGE-SECRET-KEY found"):
            load_identity(key_file)

    def test_only_comments_raises(self, tmp_path: Path) -> None:
        key_file = tmp_path / "comments.key"
        key_file.write_text("# just a comment\n# another comment\n")

        with pytest.raises(CryptoError, match="no AGE-SECRET-KEY found"):
            load_identity(key_file)

    def test_invalid_key_raises(self, tmp_path: Path) -> None:
        key_file = tmp_path / "bad.key"
        key_file.write_text("AGE-SECRET-KEY-INVALID\n")

        with pytest.raises(CryptoError, match="invalid age identity"):
            load_identity(key_file)

    def test_key_without_comments(self, age_keypair: AgeKeyPair, tmp_path: Path) -> None:
        key_file = tmp_path / "bare.key"
        key_file.write_text(f"{age_keypair.identity}\n")

        result = load_identity(key_file)

        assert str(result.identity) == str(age_keypair.identity)

    def test_key_with_blank_lines(self, age_keypair: AgeKeyPair, tmp_path: Path) -> None:
        key_file = tmp_path / "spaced.key"
        key_file.write_text(f"\n\n# comment\n\n{age_keypair.identity}\n\n")

        result = load_identity(key_file)

        assert str(result.identity) == str(age_keypair.identity)


class TestEncryptDecrypt:
    def test_roundtrip(self, age_keypair: AgeKeyPair) -> None:
        plaintext = b"sensitive data"

        ciphertext = age_encrypt(plaintext, age_keypair.recipient)
        decrypted = age_decrypt(ciphertext, age_keypair.identity)

        assert decrypted == plaintext

    def test_empty_plaintext_roundtrip(self, age_keypair: AgeKeyPair) -> None:
        ciphertext = age_encrypt(b"", age_keypair.recipient)
        decrypted = age_decrypt(ciphertext, age_keypair.identity)

        assert decrypted == b""

    def test_large_data_roundtrip(self, age_keypair: AgeKeyPair) -> None:
        plaintext = b"x" * 100_000

        ciphertext = age_encrypt(plaintext, age_keypair.recipient)
        decrypted = age_decrypt(ciphertext, age_keypair.identity)

        assert decrypted == plaintext

    def test_wrong_key_fails(self) -> None:
        key1 = x25519.Identity.generate()
        key2 = x25519.Identity.generate()

        ciphertext = age_encrypt(b"secret", key1.to_public())

        with pytest.raises(CryptoError, match="decryption failed"):
            age_decrypt(ciphertext, key2)

    def test_corrupt_ciphertext_fails(self, age_keypair: AgeKeyPair) -> None:
        with pytest.raises(CryptoError, match="decryption failed"):
            age_decrypt(b"not valid ciphertext", age_keypair.identity)

    def test_ciphertext_is_nondeterministic(self, age_keypair: AgeKeyPair) -> None:
        plaintext = b"same data"

        ct1 = age_encrypt(plaintext, age_keypair.recipient)
        ct2 = age_encrypt(plaintext, age_keypair.recipient)

        assert ct1 != ct2
        assert age_decrypt(ct1, age_keypair.identity) == plaintext
        assert age_decrypt(ct2, age_keypair.identity) == plaintext


class TestContentHash:
    def test_deterministic(self) -> None:
        assert content_hash(b"data") == content_hash(b"data")

    def test_different_data_different_hash(self) -> None:
        assert content_hash(b"data1") != content_hash(b"data2")

    def test_returns_hex_string(self) -> None:
        h = content_hash(b"test")
        assert all(c in "0123456789abcdef" for c in h)


class TestIsAgeFile:
    def test_age_extension(self) -> None:
        assert is_age_file(Path("file.age"))

    def test_nested_age_file(self) -> None:
        assert is_age_file(Path(".config/secret.age"))

    def test_non_age_file(self) -> None:
        assert not is_age_file(Path("file.txt"))

    def test_no_extension(self) -> None:
        assert not is_age_file(Path("bashrc"))

    def test_age_in_name_not_extension(self) -> None:
        assert not is_age_file(Path("age.txt"))

    def test_double_extension(self) -> None:
        assert is_age_file(Path("file.conf.age"))


class TestAgeToDecryptedPath:
    def test_simple(self) -> None:
        repo = Path("/repo")
        result = age_to_decrypted_path(repo, repo / "secret.age")
        assert result == repo / ".decrypted" / "secret"

    def test_nested(self) -> None:
        repo = Path("/repo")
        result = age_to_decrypted_path(repo, repo / ".config" / "app.conf.age")
        assert result == repo / ".decrypted" / ".config" / "app.conf"

    def test_deeply_nested(self) -> None:
        repo = Path("/repo")
        result = age_to_decrypted_path(repo, repo / "a" / "b" / "c" / "file.age")
        assert result == repo / ".decrypted" / "a" / "b" / "c" / "file"


class TestAgeToHomePath:
    def test_simple(self) -> None:
        repo = Path("/repo")
        home = Path("/home/user")
        result = age_to_home_path(repo, home, repo / "secret.age")
        assert result == home / "secret"

    def test_nested(self) -> None:
        repo = Path("/repo")
        home = Path("/home/user")
        result = age_to_home_path(repo, home, repo / ".config" / "app.conf.age")
        assert result == home / ".config" / "app.conf"


class TestHomeToAgePath:
    def test_simple(self) -> None:
        repo = Path("/repo")
        home = Path("/home/user")
        result = home_to_age_path(repo, home, home / "secret")
        assert result == repo / ("secret" + AGE_EXTENSION)

    def test_nested(self) -> None:
        repo = Path("/repo")
        home = Path("/home/user")
        result = home_to_age_path(repo, home, home / ".config" / "app.conf")
        assert result == repo / ".config" / ("app.conf" + AGE_EXTENSION)

    def test_dotfile(self) -> None:
        repo = Path("/repo")
        home = Path("/home/user")
        result = home_to_age_path(repo, home, home / ".bashrc")
        assert result == repo / (".bashrc" + AGE_EXTENSION)
