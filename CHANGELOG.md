# Changelog

## 0.2.0 (unreleased)

- M2: snapshots of selected regions (byte cap, chunked, cancellable), typed scans,
  snapshot comparison, candidate narrowing, change timeline, session export.
- Desktop window (PySide6) that waits for the game and attaches automatically, with
  snapshot/search/live-value controls and a log view.
- `.bat` launchers (one also starts the game through Steam) and a CI-built Windows `.exe`
  zip published as the `latest-build` pre-release.
- Real-game search fixes: "value shown in game" filter (a float that displays as `n`),
  float32 as the default type, New scan / Next scan workflow where a next scan re-reads only
  the candidate addresses, numpy-vectorised scans, smallest regions captured first, 2 GiB
  default snapshot limit adjustable in the window.

## 0.1.0 (unreleased)

- M0: repository structure, typed TOML configuration, logging, JSON persistence, CI,
  documentation (architecture, technical risks, Windows memory access, feasibility, safety
  policy, milestones).
- M1: read-only process discovery (Toolhelp snapshot, image path, architecture, access
  probing) and memory-region inspection (`VirtualQueryEx`) with filtering, summaries,
  cancellation and a CLI (`aoe2mr info | processes | inspect`).
- Synthetic target process (`python -m aoe2mr.synthetic.target`) for controlled experiments.
