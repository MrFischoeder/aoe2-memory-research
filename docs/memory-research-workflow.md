# Finding a value with snapshots and filters

This is the M2 workflow, shown with wood. It works the same for any number you can see on
screen. Use it in single-player only.

## Known value (fastest)

1. Start a single-player game and the research window (it attaches automatically).
2. **Memory Research** tab: type `float32`, filter **value shown in game**, value = the wood
   number on screen (for example `200`). Press **New scan** (or Enter).
   This takes one snapshot, searches it and frees it. Expect many candidates.
3. Change the value in the game (gather or spend wood).
4. Type the new number and press **Next scan** (or Enter). Only the candidate addresses are
   re-read from the game, so this takes a moment, not a full snapshot.
5. Repeat 3-4 until only a few candidates remain.
6. Tick **Live values** and watch them follow the game. Add notes as you go
   ("expected 240 after villager drop-off") and **Save session**.

Why `float32` and **value shown in game**: AoE2 is believed to store resources as floats
(not yet validated), and the screen shows a whole number. "Value shown in game" `n` accepts
any value in `[n - 0.5, n + 1)`, so both rounding and truncation match. If nothing survives,
try `int32` with **exact value**.

Other filters for **Next scan**: **increased by** / **decreased by** a value, **changed**,
**unchanged**, **increased**, **decreased**, and **exact value** with a tolerance.

## Unknown value

When the number is not shown exactly (an internal timer, a cooldown):

1. Choose a type and **changed** (or any filter without a value) and press **New scan**.
   This only stores a baseline snapshot.
2. Let the value change, choose **changed** / **increased** / **decreased** and press
   **Next scan**. This compares a new snapshot with the baseline (unchanged pages are skipped).
3. Keep pressing **Next scan** with **unchanged** / **increased** / ... to narrow down; from
   here on only the candidates are read.

## What a result means and what it does not

- A surviving address is a *candidate*, not a validated game value. Copies (UI caches,
  statistics) can follow the real value; the synthetic target's `display_*` fields reproduce
  this. Validation across independent experiments is milestone M3.
- Addresses change every time the game starts. A candidate from yesterday means nothing
  today; M3/M4 will look for stable ways to find the value again.
- Snapshot size is capped by `sampling.max_snapshot_bytes` (2 GiB by default; the
  **Snapshot limit (MiB)** box changes it for the session). Smallest regions are read first,
  so a truncated snapshot misses only the largest allocations. The timeline shows
  "X MiB of Y MiB" and says when a snapshot was truncated. At most two snapshots exist at
  once (only for unknown-value searches), so peak memory use is about twice the cap.

## Practising without the game

```powershell
python -m aoe2mr.synthetic.target          # prints pid and address
aoe2mr-gui --pid <pid>                     # or "Attach" in the Process Monitor tab
```

Then type `add wood 25`, `tick`, `set gold 500` into the target's console between snapshots.
