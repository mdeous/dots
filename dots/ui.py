from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.theme import Theme

THEME = Theme(
    {
        "ok": "green",
        "add": "bold green",
        "replace": "cyan",
        "missing": "red",
        "conflict": "yellow",
        "arrow": "dim",
        "debug": "dim magenta",
        "error": "bold red",
        "meta": "dim",
        "section": "bold",
    }
)


def make_console(*, stderr: bool) -> Console:
    return Console(theme=THEME, stderr=stderr, highlight=False)


@dataclass
class UI:
    verbose: bool = False
    out: Console = field(init=False, repr=False, default_factory=lambda: make_console(stderr=False))
    err: Console = field(init=False, repr=False, default_factory=lambda: make_console(stderr=True))

    # lower-level (free-form messages)

    def debug(self, msg: str) -> None:
        if self.verbose:
            self.out.print(f"  [debug]•[/] [meta]{escape(msg)}[/]")

    def info(self, msg: str) -> None:
        self.out.print(escape(msg))

    def notice(self, msg: str) -> None:
        self.out.print(f"[bold]{escape(msg)}[/]")

    def warning(self, msg: str) -> None:
        self.err.print(f"  [conflict]![/] {escape(msg)}")

    def error(self, msg: str) -> None:
        self.err.print(f"[error]✗ {escape(msg)}[/]")

    # semantic helpers

    def ok(self, path: Path, *, encrypted: bool = False) -> None:
        tag = " [meta](encrypted)[/]" if encrypted else ""
        self.out.print(f"  [ok]✓[/] {escape(str(path))}{tag}")

    def installed(self, path: Path, *, encrypted: bool = False) -> None:
        tag = " [meta](encrypted)[/]" if encrypted else ""
        self.out.print(f"  [add]+[/] [bold]{escape(str(path))}[/]{tag}")

    def replaced(self, path: Path, *, encrypted: bool = False) -> None:
        tag = " [meta](encrypted)[/]" if encrypted else ""
        self.out.print(f"  [replace]↻[/] {escape(str(path))}{tag}")

    def missing(self, path: Path, *, encrypted: bool = False) -> None:
        extra = ", encrypted" if encrypted else ""
        self.out.print(f"  [missing]✗[/] {escape(str(path))} [meta](missing{extra})[/]")

    def removed(self, path: Path, *, encrypted: bool = False) -> None:
        tag = " [meta](encrypted)[/]" if encrypted else ""
        self.out.print(f"  [missing]-[/] {escape(str(path))}{tag}")

    def conflict(self, path: Path, *, target: Path | None = None, reason: str = "") -> None:
        parts = [f"  [conflict]![/] {escape(str(path))}"]
        if target is not None:
            parts.append(f" [arrow]→[/] [meta]{escape(str(target))}[/]")
        if reason:
            parts.append(f" [meta]({escape(reason)})[/]")
        self.err.print("".join(parts))

    # formatting helpers

    def section(self, title: str, *, emoji: str = "") -> None:
        prefix = f"{emoji} " if emoji else ""
        self.out.print(f"\n{prefix}[section]{escape(title)}[/]\n")

    def summary(self, *, changed: int, unchanged: int) -> None:
        if changed == 0:
            self.out.print(f"\n[meta]{unchanged} unchanged[/]")
            return
        self.out.print(f"\n🎉 [bold]{changed}[/] changed, [meta]{unchanged} unchanged[/]")

    # prompts

    def ask_yesno(self, prompt: str, *, default: bool = False) -> bool:
        if not sys.stdin.isatty():
            return default
        return typer.confirm(prompt, default=default)
