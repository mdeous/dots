from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from pyrage import decrypt, encrypt, x25519

from dots.errors import CryptoError

AGE_EXTENSION = ".age"
DECRYPTED_DIR = ".decrypted"


@dataclass(frozen=True)
class AgeKeyPair:
    identity: x25519.Identity
    recipient: x25519.Recipient


def load_identity(identity_path: Path) -> AgeKeyPair:
    """
    Read an age identity file and return the keypair.

    The file format is the standard age key file: comment lines start
    with ``#``, the secret key line starts with ``AGE-SECRET-KEY-``.
    """
    try:
        text = identity_path.read_text().strip()
    except OSError as e:
        raise CryptoError(f"cannot read identity file: {e}", identity_path) from e

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("AGE-SECRET-KEY-"):
            try:
                identity = x25519.Identity.from_str(line)
            except Exception as e:
                raise CryptoError(f"invalid age identity: {e}", identity_path) from e
            return AgeKeyPair(identity=identity, recipient=identity.to_public())

    raise CryptoError("no AGE-SECRET-KEY found in identity file", identity_path)


def age_encrypt(plaintext: bytes, recipient: x25519.Recipient) -> bytes:
    try:
        return encrypt(plaintext, [recipient])
    except Exception as e:
        raise CryptoError(f"encryption failed: {e}") from e


def age_decrypt(ciphertext: bytes, identity: x25519.Identity) -> bytes:
    try:
        return decrypt(ciphertext, [identity])
    except Exception as e:
        raise CryptoError(f"decryption failed: {e}") from e


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def is_age_file(path: Path) -> bool:
    return path.suffix == AGE_EXTENSION


def age_to_decrypted_path(repo_path: Path, age_file: Path) -> Path:
    """
    Map a ``.age`` repo file to its decrypted working copy path.

    Example: ``repo/.config/secret.age`` -> ``repo/.decrypted/.config/secret``
    """
    relpath = age_file.relative_to(repo_path)
    return repo_path / DECRYPTED_DIR / relpath.with_suffix("")


def age_to_home_path(repo_path: Path, home_path: Path, age_file: Path) -> Path:
    """
    Map a ``.age`` repo file to the home symlink path.

    Example: ``repo/.config/secret.age`` -> ``home/.config/secret``
    """
    relpath = age_file.relative_to(repo_path)
    return home_path / relpath.with_suffix("")


def home_to_age_path(repo_path: Path, home_path: Path, target: Path) -> Path:
    """
    Map a home file to its ``.age`` repo path.

    Example: ``home/.config/secret`` -> ``repo/.config/secret.age``
    """
    relpath = target.relative_to(home_path)
    return repo_path / (relpath.as_posix() + AGE_EXTENSION)
