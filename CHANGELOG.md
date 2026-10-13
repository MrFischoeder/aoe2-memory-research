# Changelog

## 0.1.0 (unreleased)

- M0: repository structure, typed TOML configuration, logging, JSON persistence, CI,
  documentation (architecture, technical risks, Windows memory access, feasibility, safety
  policy, milestones).
- M1: read-only process discovery (Toolhelp snapshot, image path, architecture, access
  probing) and memory-region inspection (`VirtualQueryEx`) with filtering, summaries,
  cancellation and a CLI (`aoe2mr info | processes | inspect`).
- Synthetic target process (`python -m aoe2mr.synthetic.target`) for controlled experiments.
