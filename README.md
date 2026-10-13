# AoE2 Memory Research & Strategic Assistant

A Windows desktop **research** tool for *Age of Empires II: Definitive Edition* (Steam). It
investigates, strictly read-only and in single-player only, whether useful gameplay
information can be observed in the game's process memory, and (in later milestones) turns
validated observations into rule-based strategic advice.

> **Status: milestones M0 and M1 are implemented.** Snapshots, experiments, the game-state
> model, the advisor and the PySide6 UI are planned (see [docs/milestones.md](docs/milestones.md)).

## Safety boundaries

This project is an observer, never a participant:

- Read-only: the only process rights ever requested are `PROCESS_QUERY_LIMITED_INFORMATION`,
  `PROCESS_QUERY_INFORMATION` and `PROCESS_VM_READ`, enforced by an allowlist before
  `OpenProcess` is called.
- No memory writes, no code or DLL injection, no drivers, no debug privileges, no
  anti-cheat bypass, no simulated mouse or keyboard input.
- Single-player only. Do not run it during multiplayer or ranked games.
- No hidden-information use: the advisor will only use what the player can legitimately see.
- Nothing runs in the background unless you start it.

Details and how they are enforced: [docs/safety-policy.md](docs/safety-policy.md).

## Requirements

- Windows 10/11 64-bit, **64-bit** Python 3.11+
- Age of Empires II: DE (Steam) for the real-game milestones; not needed for M0/M1 tests
- Run the tool and the game at the same privilege level (normally: neither as administrator)

## Quick start (PowerShell)

```powershell
git clone https://github.com/MrFischoeder/aoe2-memory-research.git
cd aoe2-memory-research
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"

python -m pytest                    # unit + Windows integration tests
aoe2mr info                         # Python bitness, elevation, configured targets
aoe2mr processes                    # find AoE2DE_s.exe and report access level
aoe2mr processes --all --filter steam
aoe2mr inspect                      # region overview of the running game
aoe2mr inspect --pid 1234 --readable-only --limit 20 --save
```

### Try it on the synthetic target (no game needed)

```powershell
# terminal 1: prints {"event": "ready", "pid": ..., "address": ...}
python -m aoe2mr.synthetic.target
# terminal 2
aoe2mr inspect --pid <pid from terminal 1> --readable-only
```

Type commands such as `add wood 25`, `tick 5`, `realloc` or `quit` into terminal 1. See
[docs/synthetic-target.md](docs/synthetic-target.md).

Saved reports go to `research_data/` (git-ignored). Override settings with
`--config my.toml`; start from [config/user_config.example.toml](config/user_config.example.toml).

## Documentation

| Document | Contents |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Modules, dependency rules, interfaces, folder structure |
| [docs/technical-risks.md](docs/technical-risks.md) | Risks and mitigations |
| [docs/windows-memory-access.md](docs/windows-memory-access.md) | Windows access rights, integrity levels, compatibility |
| [docs/feasibility.md](docs/feasibility.md) | Feasibility without bypassing protections; alternative data sources |
| [docs/safety-policy.md](docs/safety-policy.md) | Hard limits and their enforcement |
| [docs/synthetic-target.md](docs/synthetic-target.md) | The synthetic test process and its protocol |
| [docs/milestones.md](docs/milestones.md) | M0-M7 scope, acceptance criteria, status |

## Repository layout

```
src/aoe2mr/
  backends/            OS access behind interfaces (Windows ctypes + in-memory fake)
    win32/             read-only Win32 bindings, access-right allowlist
  process_discovery/   find AoE2 DE, report path / architecture / access level   (M1)
  memory_research/     region enumeration, decoding, summaries                    (M1)
  snapshot_analysis/   snapshots and comparison                                   (M2)
  experiment_manager/  controlled experiments, candidate validation               (M3)
  game_state/          source-independent game-state model with UNKNOWN           (M5)
  strategy_engine/     deterministic rule-based advisor                           (M6)
  desktop_ui/          PySide6 interface                                          (M7)
  persistence/         JSON result store
  synthetic/           synthetic target process
  config.py  app_logging.py  errors.py  concurrency.py  cli.py
tests/                 pytest suite (Windows-only tests skip elsewhere)
docs/                  design and research documentation
config/                example user configuration
```
