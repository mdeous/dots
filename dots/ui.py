from __future__ import annotations

import sys
from dataclasses import dataclass

import typer


@dataclass
class UI:
    """Thin terminal output helper.

    Keeps ``repo.py`` decoupled from Typer's styling module. ``error`` reports
    without terminating — termination belongs in the CLI error handler.
    """

    verbose: bool = False

    def debug(self, msg: str) -> None:
        if self.verbose:
            typer.secho(msg, fg=typer.colors.MAGENTA)

    def info(self, msg: str) -> None:
        typer.secho(msg, fg=typer.colors.GREEN)

    def notice(self, msg: str) -> None:
        typer.secho(msg, fg=typer.colors.GREEN, bold=True)

    def warning(self, msg: str) -> None:
        typer.secho(msg, fg=typer.colors.YELLOW, err=True)

    def error(self, msg: str) -> None:
        typer.secho(msg, fg=typer.colors.RED, bold=True, err=True)

    def ask_yesno(self, prompt: str, *, default: bool = False) -> bool:
        """Interactive yes/no prompt. Returns ``default`` on EOF (non-interactive)."""
        if not sys.stdin.isatty():
            return default
        return typer.confirm(prompt, default=default)
