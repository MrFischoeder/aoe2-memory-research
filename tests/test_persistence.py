from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from aoe2mr.backends.fake import FakeProcessBackend
from aoe2mr.config import RegionsConfig
from aoe2mr.memory_research.regions import RegionInspector
from aoe2mr.persistence.json_store import ResultStore
from tests.conftest import AOE_PID


def test_save_and_load_region_report(tmp_path: Path, fake_backend: FakeProcessBackend) -> None:
    report = RegionInspector(fake_backend, RegionsConfig()).inspect(AOE_PID)
    store = ResultStore(tmp_path)
    path = store.save("region_report", report, now=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))
    assert path.name == "region_report_20260102T030405_000000Z.json"
    assert not list(tmp_path.rglob("*.tmp"))
    doc = store.load(path)
    payload = doc["payload"]
    assert doc["schema_version"] == 1 and doc["kind"] == "region_report"
    assert payload["pid"] == AOE_PID
    first = payload["regions"][0]
    assert first["protect"]["label"] == "R" and first["is_readable"] is True
    assert first["state"] == "commit"
    assert store.list("region_report") == [path]


def test_kind_validated(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        ResultStore(tmp_path).save("../escape", {})


def test_schema_checked(tmp_path: Path) -> None:
    bad = tmp_path / "x.json"
    bad.write_text('{"schema_version": 99}')
    with pytest.raises(ValueError):
        ResultStore(tmp_path).load(bad)
