from __future__ import annotations

from pathlib import Path

import pytest
from pyrage import x25519

from dots.crypto import AgeKeyPair
from dots.repo import DotRepository
from dots.ui import UI


class StubUI(UI):
    def __init__(self, *, yesno_answer: bool = True) -> None:
        super().__init__(verbose=False)
        self.yesno_answer = yesno_answer

    def ask_yesno(self, prompt: str, *, default: bool = False) -> bool:
        return self.yesno_answer


@pytest.fixture()
def fake_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    return home


@pytest.fixture()
def fake_repo(fake_home: Path) -> Path:
    repo = fake_home / ".dotrepo"
    repo.mkdir()
    return repo


@pytest.fixture()
def stub_ui() -> StubUI:
    return StubUI()


@pytest.fixture()
def dot_repo(fake_home: Path, fake_repo: Path, stub_ui: StubUI) -> DotRepository:
    return DotRepository(
        path=fake_repo,
        home=fake_home,
        ignored=(),
        git=None,
        ui=stub_ui,
    )


@pytest.fixture()
def age_keypair() -> AgeKeyPair:
    ident = x25519.Identity.generate()
    return AgeKeyPair(identity=ident, recipient=ident.to_public())


@pytest.fixture()
def age_identity_file(tmp_path: Path, age_keypair: AgeKeyPair) -> Path:
    key_file = tmp_path / "test.key"
    key_file.write_text(f"# created: 2024-01-01\n# public key: {age_keypair.recipient}\n{age_keypair.identity}\n")
    return key_file


@pytest.fixture()
def dot_repo_encrypted(fake_home: Path, fake_repo: Path, stub_ui: StubUI, age_keypair: AgeKeyPair) -> DotRepository:
    return DotRepository(
        path=fake_repo,
        home=fake_home,
        ignored=(),
        git=None,
        ui=stub_ui,
        age_keypair=age_keypair,
    )
