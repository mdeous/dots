# dots

`dots` is yet another dotfiles management tool.

TODO: badges, plenty of them!

## Features

- dotfiles stored in a central folder and symlinked by `dots` to their real location
- handles versioning, Git knowledge should not be required to use `dots`
- can store multiple machines configuration (one branch per machine, named after its hostname)
- private files (SSH keys, configuration files containing credentials, etc.) can be stored encrypted

## Dependencies

TODO

## Installation

TODO

## Configuration

The `dots` configuration file should be located at `${HOME}/.dots.conf`, and is organized in sections
in the same way as a `.ini` file. The configuration file can handle settings for multiple machines, so
that it also can be synced (by default, `dots` automatically adds its configuration when the repo is
initialized).

The global section is `DEFAULT` (case-sensitive), which holds default values that can be overriden for in
the other sections. Each machine settings are stored in a separate section named after the machine hostname.

The values that can be used in each sections are :

- `repo_dir` : custom repository path (default: `~/dots`)
- `gpg_key_id` : ID of the GPG key to use for file encryption (default: none)
- `ignored_files` : comma-separated list of files that should'nt be synced

An example configuration can be found in the `sample-config.conf` file located in the same folder as this
README.

## Usage

TODO

## Files layout

- `dots` configuration file is `${HOME}/.dots.conf`
- dotfiles are stored in `${HOME}/dots/files`
- encrypted files are stored in `${HOME}/dots/encrypted`
- decrypted files (symlink targets) are not versioned and are stored in `${HOME}/dots/decrypted`

## License

This project is licensed under the BSD 3-clause license.
