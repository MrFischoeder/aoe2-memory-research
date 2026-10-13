# Synthetic target process

`python -m aoe2mr.synthetic.target` is a tiny, developer-controlled program that keeps a known
"game state" in its **own** memory. It gives the scanner ground truth for M2/M3 before the real
game is ever inspected. It only changes its own memory, and only on command.

## Memory layout

A ctypes structure at a stable address (natural alignment, little-endian):

| Field | Type | Initial | Purpose |
|---|---|---|---|
| `magic` | uint64 | `b"AOE2SYNT"` | Locate the structure by signature |
| `food`, `wood`, `gold`, `stone` | int32 | 200/200/100/200 | Resources |
| `population`, `population_cap` | int16 | 4 / 5 | Population |
| `age` | uint8 | 1 | Current age |
| `game_time` | float32 | 0.0 | Seconds; exercises float search |
| `villagers` | int32 | 3 | Related value for cross-checks |
| `display_food`, `display_wood` | int32 | copies | Lagging "UI cache" copies, refreshed only by `tick` (decoys for candidate validation) |

Exact offsets are printed in the handshake.

## Protocol

stdin: one command per line. stdout: one JSON object per line.

```
{"event": "ready", "pid": 1234, "address": 2412345678912, "size": 48,
 "magic": ..., "layout": {"wood": {"offset": 12, "type": "int32", "size": 4}, ...},
 "values": {...}}
```

| Command | Effect |
|---|---|
| `get` | Print current values |
| `set <field> <value>` | Set a field |
| `add <field> <delta>` | Add to a field |
| `tick [seconds]` | Advance `game_time` (default 1) and refresh `display_*` |
| `realloc` | Copy the state to a new allocation and zero the old magic (simulates address instability between runs) |
| `quit` | Exit |

Errors produce `{"event": "error", "message": ...}` and the process keeps running.

## Example experiment (manual, M1)

1. Start the target, note `pid` and `address`.
2. `aoe2mr inspect --pid <pid> --readable-only` and confirm the region containing `address`
   is committed, private and `RW`.
3. The Windows integration test (`tests/test_windows_integration.py`) automates this and
   additionally verifies a read-only read of `wood` before and after `add wood 25`.
