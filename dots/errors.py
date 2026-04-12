from pathlib import Path


class DotsError(Exception):
    """
    Base class for all dots errors the CLI is expected to handle.
    """


class ConfigError(DotsError):
    """
    Configuration file is missing, unreadable, or invalid.
    """


class RepoError(DotsError):
    """
    Dotfiles repository is missing or malformed.
    """


class NotInHomeError(DotsError):
    """
    Target file is not under the user's home directory.
    """

    def __init__(self, path: Path, home: Path) -> None:
        super().__init__(f"{path} is not inside {home}")
        self.path = path
        self.home = home


class NotInRepoError(DotsError):
    """
    An operation expected a file inside the repository.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is not a repository file")
        self.path = path


class AlreadyInRepoError(DotsError):
    """
    Trying to add a file that is already tracked.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is already in the repository")
        self.path = path


class InvalidTargetError(DotsError):
    """
    Target file is of an unexpected kind (e.g. a dangling symlink).
    """

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.path = path


class FsError(DotsError):
    """
    Atomic filesystem primitive fails and has been rolled back.
    """

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.path = path


class CryptoError(DotsError):
    """
    Age encryption or decryption failure.
    """

    def __init__(self, message: str, path: Path | None = None) -> None:
        super().__init__(message)
        self.path = path
