from __future__ import annotations

import sys
from pathlib import Path

import pytest

from redberry_webkit.env_resolver import resolve_env_path


def test_env_file_var_wins_over_everything(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENV_FILE", str(tmp_path / "docker.env"))
    monkeypatch.setattr(sys, "argv", ["prog", "--env-file", str(tmp_path / "cli.env")])
    assert resolve_env_path() == tmp_path / "docker.env"


def test_cli_flag_wins_when_env_file_var_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ENV_FILE", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog", "--env-file", str(tmp_path / "cli.env")])
    assert resolve_env_path() == tmp_path / "cli.env"


def test_falls_back_to_nearest_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ENV_FILE", raising=False)
    monkeypatch.setattr(sys, "argv", ["prog"])
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert resolve_env_path() == env_file
