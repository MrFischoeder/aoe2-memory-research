# Milestones

| ID | Scope | Status |
|---|---|---|
| M0 | Repository structure, configuration, logging, persistence, documentation, CI, tests | **Done** |
| M1 | Process discovery and read-only memory-region inspection; synthetic target | **Done** |
| M2 | Memory snapshots and comparison using the synthetic target | **Done** (awaiting approval) |
| M3 | Controlled experiments and candidate-value validation | Not started |
| M4 | Investigate permitted access to AoE2 DE process data in single-player | Not started |
| M5 | Normalized game-state model with UNKNOWN support | Not started |
| M6 | Rule-based strategic advisor | Not started |
| M7 | PySide6 UI, performance monitoring, persistence integration | Started early: window + .exe package |

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

## M2 - acceptance criteria

- [x] Snapshot selected readable regions (default: private, writable) with a byte cap,
      chunked reads, progress and cancellation; unreadable chunks are skipped and counted
- [x] Typed values: int8-64, uint8-64, float32/64 (little-endian, aligned)
- [x] First scan for a known value (`equals`, optional float tolerance)
- [x] Unknown-value search by comparing two snapshots (changed, unchanged, increased,
      decreased, increased by, decreased by); unchanged 4 KiB pages are skipped
- [x] Candidate narrowing across snapshots; stale addresses dropped
- [x] Timeline of snapshots, scans, filters and notes; session saved as JSON (no raw dumps)
- [x] Bounded memory: two snapshots kept, candidate cap
- [x] Tests on synthetic data, plus an end-to-end test against the synthetic target on Windows

## Pulled forward from M7 at the owner's request

- [x] PySide6 window: Process Monitor (auto-attach to the game, regions), Memory Research
      (snapshots, search, candidates, live values, timeline, notes, save), Logs; Game State
      and Strategic Advisor tabs are placeholders until M5/M6
- [x] One-click start: `.bat` launchers, including one that starts the game through Steam
- [x] Windows `.exe` built by CI and published as a downloadable zip after every push
