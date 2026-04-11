from pathlib import Path


class DotsError(Exception):
    """Base class for all dots errors the CLI is expected to handle."""


class ConfigError(DotsError):
    """Raised when the configuration file is missing, unreadable, or invalid."""


class RepoError(DotsError):
    """Raised when the dotfiles repository is missing or malformed."""


class NotInHomeError(DotsError):
    """Raised when a target file is not under the user's home directory."""

    def __init__(self, path: Path, home: Path) -> None:
        super().__init__(f"{path} is not inside {home}")
        self.path = path
        self.home = home


class NotInRepoError(DotsError):
    """Raised when an operation expected a file inside the repository."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is not a repository file")
        self.path = path


class AlreadyInRepoError(DotsError):
    """Raised when trying to add a file that is already tracked."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"{path} is already in the repository")
        self.path = path


class InvalidTargetError(DotsError):
    """Raised when a target file is of an unexpected kind (e.g. a dangling symlink)."""

    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.path = path


class FsError(DotsError):
    """Raised when an atomic filesystem primitive fails and has been rolled back."""

    def __init__(self, message: str, path: Path, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.path = path
        self.__cause__ = cause
