"""Typed application configuration loaded from TOML.

The packaged ``default_config.toml`` is always loaded first; an optional user file
overrides individual keys. Unknown keys are rejected so typos surface early.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a configuration file is malformed or contains invalid values."""


@dataclass(frozen=True)
class DiscoveryConfig:
    target_executables: tuple[str, ...] = ("AoE2DE_s.exe",)


@dataclass(frozen=True)
class RegionsConfig:
    min_region_size: int = 4096
    max_regions: int = 200_000
    committed_only: bool = True


@dataclass(frozen=True)
class SamplingConfig:
    interval_ms: int = 1000
    max_snapshot_bytes: int = 256 * 1024 * 1024


@dataclass(frozen=True)
class PersistenceConfig:
    data_dir: Path = Path("research_data")


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file_name: str = "aoe2mr.log"
    max_bytes: int = 1024 * 1024
    backup_count: int = 3


@dataclass(frozen=True)
class AppConfig:
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)
    regions: RegionsConfig = field(default_factory=RegionsConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


def _merge(base: dict[str, Any], override: dict[str, Any], path: str = "") -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        where = f"{path}{key}"
        if key not in base:
            raise ConfigError(f"Unknown configuration key: {where}")
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ConfigError(f"Expected a table for {where}")
            merged[key] = _merge(base[key], value, f"{where}.")
        else:
            merged[key] = value
    return merged


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def _build(raw: dict[str, Any]) -> AppConfig:
    try:
        d = raw["discovery"]
        targets = tuple(str(name) for name in d["target_executables"])
        _require(len(targets) > 0, "discovery.target_executables must not be empty")

        r = raw["regions"]
        regions = RegionsConfig(
            min_region_size=int(r["min_region_size"]),
            max_regions=int(r["max_regions"]),
            committed_only=bool(r["committed_only"]),
        )
        _require(regions.min_region_size >= 0, "regions.min_region_size must be >= 0")
        _require(regions.max_regions > 0, "regions.max_regions must be > 0")

        s = raw["sampling"]
        sampling = SamplingConfig(
            interval_ms=int(s["interval_ms"]),
            max_snapshot_bytes=int(s["max_snapshot_bytes"]),
        )
        _require(sampling.interval_ms >= 50, "sampling.interval_ms must be >= 50")
        _require(sampling.max_snapshot_bytes > 0, "sampling.max_snapshot_bytes must be > 0")

        p = raw["persistence"]
        persistence = PersistenceConfig(data_dir=Path(str(p["data_dir"])))

        lg = raw["logging"]
        logging_cfg = LoggingConfig(
            level=str(lg["level"]).upper(),
            file_name=str(lg["file_name"]),
            max_bytes=int(lg["max_bytes"]),
            backup_count=int(lg["backup_count"]),
        )
        _require(logging_cfg.level in _LOG_LEVELS, f"logging.level must be one of {_LOG_LEVELS}")
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ConfigError):
            raise
        raise ConfigError(f"Invalid configuration: {exc}") from exc

    return AppConfig(
        discovery=DiscoveryConfig(target_executables=targets),
        regions=regions,
        sampling=sampling,
        persistence=persistence,
        logging=logging_cfg,
    )


def load_default_raw() -> dict[str, Any]:
    text = resources.files("aoe2mr").joinpath("default_config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def load_config(user_file: Path | None = None) -> AppConfig:
    """Load the packaged defaults, optionally overridden by ``user_file``."""
    raw = load_default_raw()
    if user_file is not None:
        try:
            override = tomllib.loads(user_file.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"Cannot read config file {user_file}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {user_file}: {exc}") from exc
        raw = _merge(raw, override)
    return _build(raw)
