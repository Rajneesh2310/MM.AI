"""Tests for MM.AI data-root resolution."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config  # noqa: E402


def test_mm_data_root_is_direct_data_folder(tmp_path, monkeypatch):
    data = tmp_path / "mm-web-data"
    monkeypatch.setenv("MM_DATA_ROOT", str(data))
    monkeypatch.setenv("MM_INSTALL_ROOT", str(tmp_path / "legacy-install"))

    assert config.data_root() == data.resolve()
    assert config.cash_root() == data.resolve() / "cash"
    assert config.fo_root() == data.resolve() / "fo"


def test_mm_install_root_remains_legacy_fallback(tmp_path, monkeypatch):
    install = tmp_path / "MMMarket"
    monkeypatch.delenv("MM_DATA_ROOT", raising=False)
    monkeypatch.setenv("MM_INSTALL_ROOT", str(install))

    assert config.install_root() == install.resolve()
    assert config.data_root() == install.resolve() / "data"


def test_linux_default_matches_mmweb_vps_data_root(monkeypatch):
    monkeypatch.delenv("MM_DATA_ROOT", raising=False)
    monkeypatch.delenv("MM_INSTALL_ROOT", raising=False)
    monkeypatch.setattr(config.os, "name", "posix")

    assert config.data_root().as_posix() == "/opt/mm-web-data"
