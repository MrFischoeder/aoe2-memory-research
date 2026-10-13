"""Synthetic target process.

Holds a small, known "game state" at a fixed address in its *own* memory and changes it only
when told to via stdin. This lets the scanner be developed and validated against ground truth
before the real game is ever touched (project goal section 4).

Run: ``python -m aoe2mr.synthetic.target``

Protocol: one command per line on stdin, one JSON object per line on stdout.
The first line printed is a ``ready`` handshake with the PID, address and field layout.

Commands::

    get                      current values
    set <field> <value>      set a field
    add <field> <delta>      add to a field (negative allowed)
    tick [seconds]           advance game_time and refresh the delayed display copies
    realloc                  move the state to a new allocation (simulates restart instability)
    quit                     exit
"""

from __future__ import annotations

import ctypes
import json
import os
import sys
from collections.abc import Iterable
from typing import Any, TextIO

MAGIC = 0x544E_5953_3245_4F41  # b"AOE2SYNT" little-endian


class SyntheticState(ctypes.Structure):
    """Ground-truth values. ``display_*`` copies lag until ``tick`` (like a UI cache)."""

    _fields_ = [
        ("magic", ctypes.c_uint64),
        ("food", ctypes.c_int32),
        ("wood", ctypes.c_int32),
        ("gold", ctypes.c_int32),
        ("stone", ctypes.c_int32),
        ("population", ctypes.c_int16),
        ("population_cap", ctypes.c_int16),
        ("age", ctypes.c_uint8),
        ("_pad0", ctypes.c_uint8 * 3),
        ("game_time", ctypes.c_float),
        ("villagers", ctypes.c_int32),
        ("display_food", ctypes.c_int32),
        ("display_wood", ctypes.c_int32),
    ]


_CTYPE_NAMES = {
    ctypes.c_uint64: "uint64",
    ctypes.c_int32: "int32",
    ctypes.c_int16: "int16",
    ctypes.c_uint8: "uint8",
    ctypes.c_float: "float32",
}

EDITABLE_FIELDS = (
    "food", "wood", "gold", "stone", "population", "population_cap", "age", "game_time",
    "villagers",
)

INITIAL_VALUES: dict[str, int | float] = {
    "food": 200, "wood": 200, "gold": 100, "stone": 200,
    "population": 4, "population_cap": 5, "age": 1, "game_time": 0.0, "villagers": 3,
}


def layout() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for field in SyntheticState._fields_:
        name, ctype = field[0], field[1]
        if name.startswith("_"):
            continue
        result[name] = {
            "offset": getattr(SyntheticState, name).offset,
            "type": _CTYPE_NAMES[ctype],
            "size": ctypes.sizeof(ctype),
        }
    return result


class CommandError(ValueError):
    pass


class SyntheticGame:
    def __init__(self) -> None:
        self._generations: list[SyntheticState] = []  # keep old buffers alive but stale
        self.state = self._new_state()
        for name, value in INITIAL_VALUES.items():
            setattr(self.state, name, value)
        self._sync_display()

    @staticmethod
    def _new_state() -> SyntheticState:
        state = SyntheticState()
        state.magic = MAGIC
        return state

    @property
    def address(self) -> int:
        return ctypes.addressof(self.state)

    def _sync_display(self) -> None:
        self.state.display_food = self.state.food
        self.state.display_wood = self.state.wood

    def values(self) -> dict[str, int | float]:
        return {name: getattr(self.state, name) for name in layout() if name != "magic"}

    def handshake(self) -> dict[str, Any]:
        return {
            "event": "ready",
            "pid": os.getpid(),
            "address": self.address,
            "size": ctypes.sizeof(SyntheticState),
            "magic": MAGIC,
            "layout": layout(),
            "values": self.values(),
        }

    def _field(self, name: str) -> str:
        if name not in EDITABLE_FIELDS:
            raise CommandError(f"unknown field {name!r}; editable: {', '.join(EDITABLE_FIELDS)}")
        return name

    @staticmethod
    def _number(name: str, text: str) -> int | float:
        try:
            return float(text) if name == "game_time" else int(text)
        except ValueError:
            raise CommandError(f"invalid number {text!r}") from None

    def apply(self, line: str) -> dict[str, Any]:
        parts = line.split()
        if not parts:
            raise CommandError("empty command")
        cmd, args = parts[0].lower(), parts[1:]
        if cmd == "get" and not args:
            pass
        elif cmd in ("set", "add") and len(args) == 2:
            name = self._field(args[0])
            value = self._number(name, args[1])
            if cmd == "add":
                value = getattr(self.state, name) + value
            setattr(self.state, name, value)
            if getattr(self.state, name) != value:
                raise CommandError(f"value {value} does not fit field {name}")
        elif cmd == "tick" and len(args) <= 1:
            seconds = float(args[0]) if args else 1.0
            self.state.game_time += seconds
            self._sync_display()
        elif cmd == "realloc" and not args:
            old = self.state
            self._generations.append(old)
            self.state = self._new_state()
            ctypes.memmove(ctypes.addressof(self.state), ctypes.addressof(old),
                           ctypes.sizeof(SyntheticState))
            old.magic = 0  # the stale copy no longer looks valid
        elif cmd == "quit" and not args:
            return {"event": "bye"}
        else:
            raise CommandError(f"bad command: {line.strip()!r}")
        return {"event": "state", "address": self.address, "values": self.values()}


def run(stdin: Iterable[str], stdout: TextIO) -> int:
    game = SyntheticGame()

    def emit(obj: dict[str, Any]) -> None:
        stdout.write(json.dumps(obj) + "\n")
        stdout.flush()

    emit(game.handshake())
    for line in stdin:
        if not line.strip():
            continue
        try:
            result = game.apply(line)
        except CommandError as exc:
            emit({"event": "error", "message": str(exc)})
            continue
        emit(result)
        if result["event"] == "bye":
            break
    return 0


def main() -> int:
    return run(sys.stdin, sys.stdout)


if __name__ == "__main__":
    raise SystemExit(main())
