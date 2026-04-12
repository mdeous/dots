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
    context_settings={"help_option_names": ["-h", "--help"]},
)


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"dots {VERSION}")
        raise typer.Exit


def config_callback(value: Path) -> Path:
    return value.expanduser()


def load_repo(ctx: typer.Context) -> DotRepository:
    state: State = ctx.obj
    return DotRepository.load(state.config, state.ui)


class State:
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
            callback=config_callback,
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
            callback=version_callback,
            is_eager=True,
        ),
    ] = False,
) -> None:
    _ = version  # consumed by version_callback; silence unused-parameter checks
    ctx.obj = State(config=config, verbose=verbose)


@app.command("add")
def cmd_add(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="path of the file to add")],
    encrypt: Annotated[
        bool,
        typer.Option("--encrypt", "-e", help="encrypt the file with age"),
    ] = False,
) -> None:
    """
    Add a file to the repository.
    """
    load_repo(ctx).add(file, encrypt=encrypt)


@app.command("remove")
def cmd_remove(
    ctx: typer.Context,
    file: Annotated[Path, typer.Argument(help="path of the file to remove")],
) -> None:
    """
    Remove a file from the repository.
    """
    load_repo(ctx).remove(file)


@app.command("list")
def cmd_list(ctx: typer.Context) -> None:
    """
    List repository contents.
    """
    load_repo(ctx).sync(list_only=True)


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
    """
    Synchronize repository content with the filesystem.
    """
    if force_add and force_link:
        raise typer.BadParameter("--force-add and --force-link are mutually exclusive")
    load_repo(ctx).sync(
        force_relink=force_relink,
        force_add=force_add,
        force_link=force_link,
    )


# Command aliases (hidden so they don't clutter --help)
app.command("a", hidden=True)(cmd_add)
app.command("rm", hidden=True)(cmd_remove)
app.command("rem", hidden=True)(cmd_remove)
app.command("del", hidden=True)(cmd_remove)
app.command("delete", hidden=True)(cmd_remove)
app.command("l", hidden=True)(cmd_list)
app.command("ls", hidden=True)(cmd_list)
app.command("s", hidden=True)(cmd_sync)


def main() -> None:
    """
    Script entry point. Wraps ``app`` so ``DotsError`` produces clean output.
    """
    try:
        app()
    except DotsError as e:
        UI().error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
