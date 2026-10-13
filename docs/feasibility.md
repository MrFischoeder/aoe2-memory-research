# Feasibility without bypassing protections

## Short answer

Observing your **own single-player** AoE2 DE session through read-only, documented Windows
APIs appears feasible, provided the game runs at the same privilege level as the tool. Each
point below marked *to verify (M4)* is an inference, not something already confirmed, and
will be checked on the target machine before any real-game work.

## Why it is expected to work

- AoE2 DE runs as an ordinary 64-bit user process started by the logged-in user, so the
  default DACL grants that user read access (see `windows-memory-access.md`).
- No kernel-mode anti-cheat driver is known to ship with AoE2 DE that would strip handle
  rights. *To verify (M4):* check installed drivers/services and whether `OpenProcess` with
  `QUERY_INFORMATION | VM_READ` succeeds on the target machine. If access is denied for any
  reason, the project stops there: no workarounds.
- RTS games using deterministic lockstep keep the full simulation state in every client's
  memory, so in single-player the player's own economy values are expected to exist in
  process memory. *To verify (M3/M4)* via controlled experiments.

## Limits that apply even when access works

- **Multiplayer is out of scope.** In lockstep games every client also holds opponents' state,
  which is exactly how "map hacks" work. Reading it would be hidden-information exploitation
  and is prohibited here. The tool is for single-player only; do not run it during online
  games. Microsoft's terms for the game prohibit cheating in multiplayer.
- **Only information the player can see** (own resources, population, age, own units and
  buildings, game time) may feed the advisor, even in single-player.
- **No modification or automation**, ever, in this phase.

## Documented or permitted alternatives to memory reading

The project goal asks to research these before relying on memory inspection.

| Source | Live? | Notes |
|---|---|---|
| Recorded games (`.aoe2record`) | During/after the game | Written by the game itself. Format is not officially documented but has long-standing community parsers. A good candidate for an alternative `GameStateSource` and for validating memory findings offline. |
| Official live game-state API | - | None is known for AoE2 DE (unlike, for example, game-state integration APIs in some other titles). *To verify (M4).* |
| Online match/leaderboard data | No | Post-match, multiplayer metadata only; not useful for live single-player advice. |
| Screen observation | Yes | Reading the on-screen resource bar via capture + OCR uses only what the player sees and needs no process access. Higher CPU/GPU cost; planned as a future source. |
| In-game AI scripts / scenario triggers | Yes | Run inside the game; no supported channel to export data to an external tool. |

Conclusion: memory research is the most direct route for live data and is acceptable within
the read-only, single-player limits; screen observation is the most "visibly fair" fallback;
recorded games are the best offline validation source. The architecture keeps all three
interchangeable.
