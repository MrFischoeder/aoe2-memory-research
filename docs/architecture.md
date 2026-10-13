# Architecture

## Goals that shape the design

1. **Read-only by construction.** Only one module talks to Win32, and it can only request
   read-only rights.
2. **Source independence.** Game state and strategy never know where data came from, so
   memory reading can later be complemented or replaced by replay parsing or screen
   observation.
3. **Honesty about uncertainty.** Every observed value can be `UNKNOWN`; nothing is invented.
4. **Bounded cost.** No continuous full-memory scanning; every expensive operation is
   user-triggered, capped and cancellable.
5. **Testable without the game.** Everything above the backend runs against an in-memory fake
   backend or the synthetic target process.

## Layers and dependency rules

```
                 desktop_ui (M7)  /  cli
                        |
   strategy_engine (M6) |  experiment_manager (M3)
            |           |        |
       game_state (M5)  |  snapshot_analysis (M2)
            ^           |        |
            |      memory_research   process_discovery      persistence
   (adapters, M4)           \           /
                          backends.base  (Protocols)
                           /          \
              backends.windows     backends.fake
                    |
              backends.win32  (ctypes, read-only allowlist)
```

Rules (checked in review; the static safety test enforces the Win32 part):

- Only `backends/win32` imports `ctypes` Win32 functions. Only `backends/win32/api.py`
  calls `OpenProcess`, and only after `validate_access_mask`.
- Services (`process_discovery`, `memory_research`, later `snapshot_analysis`) depend on the
  `ProcessBackend` protocol, injected through constructors.
- `game_state` and `strategy_engine` must not import `backends`, `memory_research` or
  `snapshot_analysis`. Memory findings reach `game_state` through an adapter that
  implements a generic `GameStateSource` interface (M4/M5).
- Game knowledge (unit costs, tech requirements, rules) will live in data files under
  `strategy_engine`, separate from code that reads memory (M6).

## Key interfaces (M1)

```python
class ProcessBackend(Protocol):
    def list_processes(self) -> list[ProcessEntry]: ...
    def identify(self, pid: int) -> tuple[str | None, Architecture]: ...
    def open_read_only(self, pid: int) -> ReadOnlyProcess: ...
    def is_elevated(self) -> bool | None: ...

class ReadOnlyProcess(Protocol):          # context manager
    def iter_regions(self, max_regions: int) -> Iterator[MemoryRegion]: ...
    def read(self, address: int, size: int) -> bytes: ...
```

- `ProcessDiscovery(backend, DiscoveryConfig)` lists processes, finds `AoE2DE_s.exe`, and
  probes access step by step, producing `ProcessDetails` with an `AccessStatus`
  (`read`, `query_only`, `denied`, `exited`, `unsupported`). A denial is recorded and no
  further attempt is made.
- `RegionInspector(backend, RegionsConfig)` enumerates regions with `VirtualQueryEx`, filters
  them (state, size, readability), summarises bytes by type and protection and returns an
  immutable `RegionReport`. It accepts a `CancellationToken`.
- `ResultStore(data_dir)` saves any dataclass graph as versioned JSON, written atomically.

All models are frozen dataclasses with enums, so they are hashable, comparable and safe to
pass between threads.

## Snapshot analysis (M2)

`ResearchSession(backend, pid, ...)` is the single object the UI drives:
`capture()` -> `scan_value()` / `apply_filter()` -> `read_live()`, plus `annotate()`,
`reset()` and `to_record()`. It keeps two snapshots at most, stores candidates in compact
`array` objects and appends a `TimelineEvent` for every step.

## Threading model

Services are synchronous and side-effect free apart from logging. The desktop window runs
them in `QThreadPool` workers with a `CancellationToken`; long loops check it periodically.
Only one heavy operation runs at a time. Two timers exist, both only while the window is open:
the game watcher (process list only, every 2 s, no memory access) and the optional
"Live values" refresh (reads at most 200 candidate addresses per tick).

## Future data sources

```python
class GameStateSource(Protocol):          # planned for M5
    def observe(self) -> GameStateObservation: ...   # every field may be UNKNOWN
```

Planned implementations: validated memory adapter (M4), recorded-game parser, screen-based
observation. The advisor consumes `GameStateObservation` and never a raw address.

## Configuration, logging, persistence

- `src/aoe2mr/default_config.toml` holds defaults; `--config` overrides individual keys.
  Unknown keys and invalid values are rejected.
- Logs go to the console and to a rotating file in `<data_dir>/logs/`.
- Research output is JSON with a `schema_version`, under `<data_dir>/<kind>/`. Raw memory
  contents are not persisted in M1.
