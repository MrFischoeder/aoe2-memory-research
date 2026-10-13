from __future__ import annotations

import ctypes
import io
import json
import struct
import subprocess
import sys

import pytest

from aoe2mr.synthetic.target import (
    INITIAL_VALUES,
    MAGIC,
    CommandError,
    SyntheticGame,
    SyntheticState,
    layout,
    run,
)


def test_magic_bytes() -> None:
    assert struct.pack("<Q", MAGIC) == b"AOE2SYNT"


def test_layout_matches_ctypes() -> None:
    lay = layout()
    assert lay["magic"] == {"offset": 0, "type": "uint64", "size": 8}
    assert lay["wood"]["offset"] == SyntheticState.wood.offset
    assert lay["game_time"]["type"] == "float32"
    assert "_pad0" not in lay


def test_initial_state_in_memory() -> None:
    game = SyntheticGame()
    raw = ctypes.string_at(game.address, ctypes.sizeof(SyntheticState))
    assert struct.unpack_from("<Q", raw, 0)[0] == MAGIC
    assert struct.unpack_from("<i", raw, layout()["wood"]["offset"])[0] == INITIAL_VALUES["wood"]


def test_commands() -> None:
    game = SyntheticGame()
    assert game.apply("add wood 25")["values"]["wood"] == 225
    assert game.apply("set food 50")["values"]["food"] == 50
    assert game.apply("add gold -30")["values"]["gold"] == 70
    v = game.apply("get")["values"]
    assert v["display_food"] == 200 and v["display_wood"] == 200  # lagging copies
    v = game.apply("tick 2.5")["values"]
    assert v["game_time"] == pytest.approx(2.5)
    assert v["display_food"] == 50 and v["display_wood"] == 225


def test_rejected_value_leaves_state_unchanged() -> None:
    game = SyntheticGame()
    before = game.values()
    for cmd in ("set population 100000", "add population 40000", "set age 300"):
        with pytest.raises(CommandError):
            game.apply(cmd)
    assert game.values() == before


def test_float_field_accepts_non_representable_values() -> None:
    game = SyntheticGame()
    assert game.apply("set game_time 0.1")["values"]["game_time"] == pytest.approx(0.1)
    assert game.apply("tick 0.2")["values"]["game_time"] == pytest.approx(0.3)


def test_run_survives_bad_tick() -> None:
    out = io.StringIO()
    run(["tick nope\n", "get\n", "quit\n"], out)
    events = [json.loads(line)["event"] for line in out.getvalue().splitlines()]
    assert events == ["ready", "error", "state", "bye"]


def test_realloc_moves_state_and_invalidates_old_copy() -> None:
    game = SyntheticGame()
    game.apply("set stone 999")
    old_address = game.address
    result = game.apply("realloc")
    assert result["address"] != old_address
    assert result["values"]["stone"] == 999
    assert ctypes.c_uint64.from_address(old_address).value == 0
    assert ctypes.c_uint64.from_address(game.address).value == MAGIC


@pytest.mark.parametrize("cmd", ["", "fly", "set magic 1", "set wood x", "add wood",
                                 "set population 100000", "get extra", "tick nope"])
def test_bad_commands(cmd: str) -> None:
    with pytest.raises(CommandError):
        SyntheticGame().apply(cmd)


def test_run_protocol() -> None:
    out = io.StringIO()
    assert run(["add wood 10\n", "bogus\n", "\n", "quit\n", "get\n"], out) == 0
    lines = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [line["event"] for line in lines] == ["ready", "state", "error", "bye"]
    assert lines[0]["magic"] == MAGIC
    assert lines[1]["values"]["wood"] == 210


def test_subprocess_handshake() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "aoe2mr.synthetic.target"],
        input="quit\n", capture_output=True, text=True, timeout=30, check=True,
    )
    ready = json.loads(proc.stdout.splitlines()[0])
    assert ready["event"] == "ready" and ready["pid"] > 0 and ready["address"] > 0
