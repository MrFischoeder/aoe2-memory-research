from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from aoe2mr.backends.fake import FakeProcessBackend
from aoe2mr.cli import main
from tests.conftest import AOE_PID


@pytest.fixture
def run_cli(tmp_path: Path, fake_backend: FakeProcessBackend):  # type: ignore[no-untyped-def]
    cfg = tmp_path / "cfg.toml"
    cfg.write_text(f'[persistence]\ndata_dir = "{(tmp_path / "data").as_posix()}"\n')

    def _run(*argv: str, backend: FakeProcessBackend = fake_backend) -> tuple[int, str]:
        out = io.StringIO()
        code = main(["--config", str(cfg), *argv], backend_factory=lambda: backend, out=out)
        return code, out.getvalue()

    return _run


def test_processes_finds_target(run_cli) -> None:  # type: ignore[no-untyped-def]
    code, out = run_cli("processes")
    assert code == 0
    assert f"PID:           {AOE_PID}" in out and "Access:        read" in out


def test_processes_none_found(run_cli) -> None:  # type: ignore[no-untyped-def]
    code, out = run_cli("processes", backend=FakeProcessBackend([]))
    assert code == 2 and "No Age of Empires II" in out


def test_processes_all_json(run_cli) -> None:  # type: ignore[no-untyped-def]
    code, out = run_cli("processes", "--all", "--json")
    assert code == 0
    assert {p["name"] for p in json.loads(out)} >= {"AoE2DE_s.exe", "System"}


def test_inspect_target_and_save(run_cli, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    code, out = run_cli("inspect", "--save")
    assert code == 0
    assert "Regions:       4 kept, 3 skipped" in out
    assert "RW+G" in out
    saved = list((tmp_path / "data" / "region_report").glob("*.json"))
    assert len(saved) == 1
    assert json.loads(saved[0].read_text())["payload"]["process"]["access"] == "read"


def test_inspect_denied_is_error_not_crash(run_cli, capsys) -> None:  # type: ignore[no-untyped-def]
    code, _ = run_cli("inspect", "--pid", "777")
    assert code == 1
    assert "Access denied" in capsys.readouterr().err


def test_info(run_cli) -> None:  # type: ignore[no-untyped-def]
    code, out = run_cli("info")
    assert code == 0 and "Elevated:      False" in out


def test_bad_config(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    bad = tmp_path / "bad.toml"
    bad.write_text("[nope]\n")
    assert main(["--config", str(bad), "info"]) == 1
    assert "Configuration error" in capsys.readouterr().err
