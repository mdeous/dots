# dots

Yet another dotfiles management tool.

## :sparkles: Features

- :link: Dotfiles stored in a central folder and symlinked to their real location
- :repeat: Automatic git versioning on every change
- :computer: Per-machine configuration via hostname-based config sections
- :warning: Conflict detection and resolution during sync

## :clipboard: Requirements

- Python 3.12+
- git

## :package: Installation

Clone the repository and install with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/mdeous/dots.git
cd dots
uv sync
```

Or with pip:

```bash
git clone https://github.com/mdeous/dots.git
cd dots
pip install .
```

## :gear: Configuration

The configuration file should be located at `~/.dots.conf`.

Settings are organized in sections named after the machine's hostname. The `[DEFAULT]` section provides fallback values used when no hostname-specific section exists.

### Available settings

| Key             | Description                                               | Default  |
| --------------- | --------------------------------------------------------- | -------- |
| `repo_dir`      | Path to the dotfiles repository                           | `~/dots` |
| `gpg_key_id`    | GPG key ID for file encryption                            | _none_   |
| `ignored_files` | Comma-separated list of glob patterns to skip during sync | _none_   |

### Example

```ini
[DEFAULT]
repo_dir = ~/dots

[work-laptop]
repo_dir = ~/dotfiles
ignored_files = .bashrc, .config/personal/*

[home-desktop]
gpg_key_id = ABCDEF1234567890
```

## :rocket: Usage

### Global options

```text
dots [--config PATH] [--verbose] [--version] COMMAND
```

| Option      | Short | Description                                   |
| ----------- | ----- | --------------------------------------------- |
| `--config`  | `-c`  | Path to config file (default: `~/.dots.conf`) |
| `--verbose` | `-v`  | Display debug information                     |
| `--version` | `-V`  | Display version and exit                      |

### `dots add <file>`

Add a file to the repository. The file is copied into the repo and replaced with a symlink.

```bash
dots add ~/.bashrc
dots add ~/.config/git/config
```

### `dots remove <file>`

Remove a file from the repository. The symlink is replaced with the original file.

```bash
dots remove ~/.bashrc
```

### `dots list`

List all files in the repository and their sync status.

```bash
dots list
```

### `dots sync`

Synchronize the repository with the filesystem. Creates missing symlinks and detects conflicts.

```bash
dots sync
```

| Option           | Short | Description                                    |
| ---------------- | ----- | ---------------------------------------------- |
| `--force-relink` | `-r`  | Overwrite links that point to the wrong target |
| `--force-add`    | `-a`  | Overwrite the repo version with the local file |
| `--force-link`   | `-l`  | Overwrite the local file with the repo version |

`--force-add` and `--force-link` are mutually exclusive. Without force flags, `dots` prompts interactively when conflicts are found.

## :scroll: License

BSD 3-Clause. See [LICENSE](LICENSE) for details.
