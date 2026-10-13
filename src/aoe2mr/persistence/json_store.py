"""JSON result store. Files are written atomically and never contain raw memory dumps."""

from __future__ import annotations

import dataclasses
import json
import os
import re
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1
_SAFE_KIND = re.compile(r"^[a-z0-9_]+$")


def to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: to_jsonable(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        # Include computed properties that are part of the research record.
        for prop in ("label", "readable", "is_readable"):
            if hasattr(type(obj), prop) and isinstance(getattr(type(obj), prop), property):
                out[prop] = getattr(obj, prop)
        return out
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    return obj


class ResultStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def save(self, kind: str, payload: Any, *, now: datetime | None = None) -> Path:
        if not _SAFE_KIND.match(kind):
            raise ValueError(f"invalid result kind {kind!r}")
        now = now or datetime.now(UTC)
        folder = self.data_dir / kind
        folder.mkdir(parents=True, exist_ok=True)
        stamp = now.strftime("%Y%m%dT%H%M%S_%fZ")
        path = folder / f"{kind}_{stamp}.json"
        document = {
            "schema_version": SCHEMA_VERSION,
            "kind": kind,
            "saved_at": now.isoformat(),
            "payload": to_jsonable(payload),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(document, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    def load(self, path: Path) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        if document.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version in {path}")
        return document

    def list(self, kind: str) -> list[Path]:
        folder = self.data_dir / kind
        return sorted(folder.glob(f"{kind}_*.json")) if folder.is_dir() else []
