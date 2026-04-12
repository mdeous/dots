from __future__ import annotations

from pathlib import Path

import pytest

from dots.errors import ConfigError
from dots.repo import load_config


class TestLoadConfigDefaults:
    def test_no_config_file(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent.conf")
        assert config.repo_dir == Path("~/dots").expanduser().resolve()
        assert config.ignored == ()
        assert config.age_identity is None

    def test_empty_config_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "empty.conf"
        cfg.write_text("")
        config = load_config(cfg)
        assert config.repo_dir == Path("~/dots").expanduser().resolve()
        assert config.ignored == ()
        assert config.age_identity is None


class TestLoadConfigRepoDir:
    def test_custom_repo_dir(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = /custom/repo\n")
        assert load_config(cfg).repo_dir == Path("/custom/repo")

    def test_tilde_expansion(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = ~/mydots\n")
        assert load_config(cfg).repo_dir == Path("~/mydots").expanduser().resolve()

    def test_empty_repo_dir_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir =\n")
        with pytest.raises(ConfigError, match="missing 'repo_dir'"):
            load_config(cfg)


class TestLoadConfigHostname:
    def test_hostname_section_selected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("platform.node", lambda: "myhost")
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[myhost]\nrepo_dir = /host/specific\n")
        assert load_config(cfg).repo_dir == Path("/host/specific")

    def test_fallback_to_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("platform.node", lambda: "unknownhost")
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = /default/path\n")
        assert load_config(cfg).repo_dir == Path("/default/path")


class TestLoadConfigIgnoredFiles:
    def test_comma_separated_parsing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nignored_files = *.swp, *.tmp, .DS_Store\n")
        assert load_config(cfg).ignored == ("*.swp", "*.tmp", ".DS_Store")

    def test_empty_ignored_files(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nignored_files =\n")
        assert load_config(cfg).ignored == ()

    def test_no_ignored_files_key(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = ~/dots\n")
        assert load_config(cfg).ignored == ()


class TestLoadConfigAgeIdentity:
    def test_age_identity_present(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nage_identity = /path/to/key\n")
        assert load_config(cfg).age_identity == Path("/path/to/key")

    def test_age_identity_tilde_expansion(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nage_identity = ~/.age/key\n")
        assert load_config(cfg).age_identity == Path("~/.age/key").expanduser().resolve()

    def test_age_identity_absent(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nrepo_dir = ~/dots\n")
        assert load_config(cfg).age_identity is None

    def test_age_identity_empty(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nage_identity =\n")
        assert load_config(cfg).age_identity is None

    def test_age_identity_whitespace_only(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[DEFAULT]\nage_identity =   \n")
        assert load_config(cfg).age_identity is None

    def test_age_identity_in_hostname_section(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("platform.node", lambda: "myhost")
        cfg = tmp_path / "dots.conf"
        cfg.write_text("[myhost]\nage_identity = /host/key\n")
        assert load_config(cfg).age_identity == Path("/host/key")


class TestLoadConfigInvalid:
    def test_malformed_config_raises(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dots.conf"
        cfg.write_bytes(b"\x00\x00garbage[[[")
        with pytest.raises(ConfigError, match="invalid config file"):
            load_config(cfg)
