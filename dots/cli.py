from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from dots import VERSION
from dots.errors import DotsError
from dots.repo import DotRepository
from dots.ui import UI

app = typer.Typer(
    name="dots",
    help="Configuration files management tool.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_show_locals=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dots {VERSION}")
        raise typer.Exit


def _config_callback(value: Path) -> Path:
    return value.expanduser()


def _load(ctx: typer.Context) -> DotRepository:
    state: _State = ctx.obj
    return DotRepository.load(state.config, state.ui)


class _State:
    def __init__(self, config: Path, verbose: bool) -> None:
        self.config = config
        self.verbose = verbose
        self.ui = UI(verbose=verbose)


@app.callback()
def app_main(
    ctx: typer.Context,
    config: Annotated[
        Path,
        typer.Option(
            "--config",
            "-c",
            help="configuration file",
            callback=_config_callback,
        ),
    ] = Path("~/.dots.conf"),
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="display debug information"),
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            "-V",
            help="display program version and exit",
            callback=_version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    _ = version  # consumed by _version_callback; silence unused-parameter checks
    ctx.obj = _State(config=config, verbose=verbose)


@app.command("add")
def cmd_add(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="path of the file to add")],
) -> None:
    """Add a file to the repository."""
    _load(ctx).add(file)


@app.command("remove")
def cmd_remove(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="path of the file to remove")],
) -> None:
    """Remove a file from the repository."""
    _load(ctx).remove(file)


@app.command("list")
def cmd_list(ctx: typer.Context) -> None:
    """List repository contents."""
    _load(ctx).sync(list_only=True)


@app.command("sync")
def cmd_sync(
    ctx: typer.Context,
    force_relink: Annotated[
        bool,
        typer.Option(
            "--force-relink",
            "-r",
            help="if a link points to another file, overwrite without asking",
        ),
    ] = False,
    force_add: Annotated[
        bool,
        typer.Option(
            "--force-add",
            "-a",
            help="if a file already exists, overwrite the repository version",
        ),
    ] = False,
    force_link: Annotated[
        bool,
        typer.Option(
            "--force-link",
            "-l",
            help="if a file already exists, overwrite the local version",
        ),
    ] = False,
) -> None:
    """Synchronize repository content with the filesystem."""
    if force_add and force_link:
        raise typer.BadParameter(
            "--force-add and --force-link are mutually exclusive"
        )
    _load(ctx).sync(
        force_relink=force_relink,
        force_add=force_add,
        force_link=force_link,
    )


def main() -> None:
    """Script entry point. Wraps ``app`` so ``DotsError`` produces clean output."""
    try:
        app()
    except DotsError as e:
        typer.secho(f"error: {e}", fg=typer.colors.RED, bold=True, err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
