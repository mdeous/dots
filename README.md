# dots

[![CI](https://github.com/mdeous/dots/actions/workflows/ci.yml/badge.svg)](https://github.com/mdeous/dots/actions/workflows/ci.yml)
[![CodeQL](https://github.com/mdeous/dots/actions/workflows/github-code-scanning/codeql/badge.svg)](https://github.com/mdeous/dots/actions/workflows/github-code-scanning/codeql)
[![PyPI](https://img.shields.io/pypi/v/dotsman)](https://pypi.org/project/dotsman/)
![Python](https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fmdeous%2Fdots%2Fmaster%2Fpyproject.toml)
![License](https://img.shields.io/github/license/mdeous/dots)

Yet another dotfiles management tool.

## :sparkles: Features

- :link: Dotfiles stored in a central folder and symlinked to their real location
- :repeat: Automatic git versioning on every change
- :computer: Per-machine configuration via hostname-based config sections
- :warning: Conflict detection and resolution during sync
- :lock: Encryption for sensitive files

## :clipboard: Requirements

- Python 3.12+
- git

## :package: Installation

Install with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install dotsman
```

To update to the latest version:

```bash
uv tool upgrade dotsman
```

## :gear: Configuration

The configuration file should be located at `~/.dots.conf`.

Settings are organized in sections named after the machine's hostname. The `[DEFAULT]` section provides fallback values used when no hostname-specific section exists.

### Available settings

| Key             | Description                                                               | Default  |
| --------------- | ------------------------------------------------------------------------- | -------- |
| `repo_dir`      | Path to the dotfiles repository                                           | `~/dots` |
| `age_identity`  | Path to an [age](https://age-encryption.org) identity file for encryption | _none_   |
| `ignored_files` | Comma-separated list of glob patterns to skip during sync                 | _none_   |

### Example

```ini
[DEFAULT]
repo_dir = ~/dots

[work-laptop]
repo_dir = ~/dotfiles
ignored_files = .bashrc, .config/personal/*

[home-desktop]
age_identity = ~/.age/dots.key
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

### `dots add <file>` (alias: `a`)

Add a file to the repository. The file is copied into the repo and replaced with a symlink.

```bash
dots add ~/.bashrc
dots add ~/.config/git/config
```

| Option      | Short | Description                                      |
| ----------- | ----- | ------------------------------------------------ |
| `--encrypt` | `-e`  | Encrypt the file with age before storing in repo |

When `--encrypt` is used, the file is stored as a `.age` file in the repo (encrypted at rest), with a decrypted working copy in a gitignored `.decrypted/` directory. The symlink points to the decrypted copy so the file remains usable. Requires `age_identity` to be set in the config.

### `dots remove <file>` (aliases: `rm`, `rem`, `del`, `delete`)

Remove a file from the repository. The symlink is replaced with the original file.

```bash
dots remove ~/.bashrc
```

### `dots list` (aliases: `l`, `ls`)

List all files in the repository and their sync status.

```bash
dots list
```

### `dots sync` (alias: `s`)

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

## :lock: Encryption

Sensitive dotfiles can be encrypted at rest using [age](https://age-encryption.org). Encrypted files are safe to push to public repositories.

### Setup

1. Generate an age identity:

   ```bash
   age-keygen -o ~/.age/dots.key
   ```

2. Add the identity path to your config (`~/.dots.conf`):

   ```ini
   [DEFAULT]
   age_identity = ~/.age/dots.key
   ```

3. Add files with encryption:

   ```bash
   dots add --encrypt ~/.config/secrets.env
   ```

### How it works

- Encrypted files are stored in the repo with a `.age` extension (e.g., `secrets.env.age`)
- Decrypted working copies live in a gitignored `.decrypted/` directory inside the repo
- Symlinks point to the decrypted copies, so files are usable as normal
- `dots sync` detects changes to decrypted files and re-encrypts them automatically
- On a new machine, `dots sync` decrypts all `.age` files and creates symlinks
- If the age identity is not configured, encrypted files are skipped with a warning during sync

## :scroll: License

BSD 3-Clause. See [LICENSE](LICENSE) for details.
