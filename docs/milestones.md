# Milestones

| ID | Scope | Status |
|---|---|---|
| M0 | Repository structure, configuration, logging, persistence, documentation, CI, tests | **Done** |
| M1 | Process discovery and read-only memory-region inspection; synthetic target | **Done** (awaiting approval) |
| M2 | Memory snapshots and comparison using the synthetic target | Not started |
| M3 | Controlled experiments and candidate-value validation | Not started |
| M4 | Investigate permitted access to AoE2 DE process data in single-player | Not started |
| M5 | Normalized game-state model with UNKNOWN support | Not started |
| M6 | Rule-based strategic advisor | Not started |
| M7 | PySide6 UI, performance monitoring, persistence integration | Not started |

## M0 - acceptance criteria

- [x] `src/` package layout with one package per architectural module
- [x] Typed TOML configuration with validation and user overrides
- [x] Logging to console and rotating file
- [x] Versioned JSON result store
- [x] pytest suite, ruff, mypy (strict), CI on Windows and Linux
- [x] Architecture, risks, Windows access, feasibility and safety documentation

## M1 - acceptance criteria

- [x] Enumerate processes and identify `AoE2DE_s.exe` (configurable, case-insensitive)
- [x] Report PID, parent PID, architecture, executable path and access level
- [x] Only documented APIs and read-only rights; allowlist enforced and tested
- [x] Enumerate regions with size, state, protection and type; readability decoding
- [x] Summaries by type and protection; filters; region cap; cancellation
- [x] Access-denied and exited processes handled without bypass attempts
- [x] Save region reports locally
- [x] Synthetic target process with documented protocol
- [x] Integration test against the synthetic target on real Windows (CI `windows-latest`)

## Planned for M2 (preview, not started)

Snapshot of selected readable regions with byte caps, page-hash change detection, typed
diffing (int8-64, uint, float32/64), change timeline, synthetic-target-driven tests.
