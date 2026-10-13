# Technical risks and mitigations

| # | Risk | Impact | Mitigation |
|---|------|--------|------------|
| 1 | **Addresses change every run** (ASLR, heap allocation order, game patches). | Candidates found once are useless next session. | Never treat an absolute address as identity. M3/M4 record module-relative offsets, pointer paths or byte signatures and re-validate them every session. The synthetic target's `realloc` command simulates this. |
| 2 | **False candidates.** A value such as `225` occurs thousands of times; UI caches, undo buffers and statistics hold copies. | Wrong game state, wrong advice. | Multiple independent experiments per candidate, change-direction and magnitude checks, stability over time, cross-checks between related values (e.g. villagers vs population). Synthetic `display_*` fields reproduce lagging copies. |
| 3 | **Data-type ambiguity.** Resources may be `float32` (AoE engines historically store resources as floats), `int32`, or derived. | Missed or misread candidates. | M2 filters support int8-64, uint, float32/64 with tolerance; M3 records the type as part of every candidate. |
| 4 | **Non-atomic reads.** The game keeps running while we read; multi-field reads can tear. | Inconsistent snapshots. | Short targeted reads, re-read and compare, timestamps on every observation, stale/invalid flags. The process is never suspended (that would need a forbidden right). |
| 5 | **Memory and CPU cost.** The game's committed memory is large (often several GiB). | Lag in game and tool, huge snapshot files. | Region filters (private RW only by default), `max_snapshot_bytes`, chunked reads, page hashing for change detection, no continuous full scans, configurable sampling interval. |
| 6 | **Access denied** (game or tool elevated, protected processes, security software). | Feature unavailable. | Detect and report the access level (`read` / `query_only` / `denied`); explain the cause; never escalate privileges. |
| 7 | **Security software heuristics.** Tools reading other processes' memory can be flagged. | Tool quarantined or blocked. | Only documented APIs with minimal rights, no injection or hooks, readable source, no packed executables. |
| 8 | **Terms of service / fair play.** Memory tools can be misused in multiplayer. | Account risk, unfair play. | Single-player only, read-only, no hidden information, no automation. See `feasibility.md`. |
| 9 | **Game updates change layout.** | Validated mappings break. | Store game build/version and executable hash with every finding; invalidate on mismatch. |
| 10 | **Python bitness / platform.** 32-bit Python cannot fully inspect a 64-bit game; ctypes layouts differ. | Wrong structures, crashes. | Hard requirement for 64-bit Python, structure-size unit tests against SDK sizes. |
| 11 | **Hardware (i5-2500K, 4 cores).** | The game itself already uses much CPU. | Background work at low frequency, bounded batches, worker threads; measure in M7. |
| 12 | **GUI responsiveness** with large region lists (100k+ rows). | Frozen UI. | Workers + model/view with lazy loading in M7; summaries instead of full lists. |
