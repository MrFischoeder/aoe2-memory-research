from __future__ import annotations

from pathlib import Path

import pytest

from aoe2mr.config import ConfigError, load_config


def test_defaults_load() -> None:
    cfg = load_config()
    assert cfg.discovery.target_executables == ("AoE2DE_s.exe",)
    assert cfg.regions.committed_only is True
    assert cfg.logging.level == "INFO"
    assert cfg.persistence.data_dir == Path("research_data")


def test_user_override(tmp_path: Path) -> None:
    f = tmp_path / "c.toml"
    f.write_text('[regions]\nmin_region_size = 0\n[logging]\nlevel = "debug"\n')
    cfg = load_config(f)
    assert cfg.regions.min_region_size == 0
    assert cfg.regions.max_regions == 200000  # untouched default
    assert cfg.logging.level == "DEBUG"


@pytest.mark.parametrize(
    "text",
    [
        "[regions]\nunknown_key = 1\n",
        "[nonexistent]\nx = 1\n",
        "[sampling]\ninterval_ms = 1\n",
        "[logging]\nlevel = \"LOUD\"\n",
        "[discovery]\ntarget_executables = []\n",
        "regions = 5\n",
        "not toml ===",
    ],
)
def test_invalid_config_rejected(tmp_path: Path, text: str) -> None:
    f = tmp_path / "c.toml"
    f.write_text(text)
    with pytest.raises(ConfigError):
        load_config(f)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "missing.toml")


def test_example_config_matches_defaults() -> None:
    root = Path(__file__).resolve().parents[1]
    example = root / "config" / "user_config.example.toml"
    assert load_config(example) == load_config()
