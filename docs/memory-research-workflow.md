# Finding a value with snapshots and filters

This is the M2 workflow, shown with wood. It works the same for any number you can see on
screen. Use it in single-player only.

## Known value (fastest)

1. Start a single-player game and the research window (it attaches automatically).
2. **Memory Research** tab: **Take snapshot** (label: "start, wood 200").
3. Type `int32`, filter **equals value**, value `200`, **Apply**.
   Expect thousands of candidates: 200 is a common number.
4. Gather some wood in the game (for example to 225). **Take snapshot**.
5. Filter **increased by value**, value `25` (or **equals value** `225`), **Apply**.
6. Repeat steps 4-5 with different changes until only a few candidates remain.
7. Tick **Live values** and watch them follow the game. Add notes as you go
   ("expected 240 after villager drop-off") and **Save session**.

If nothing survives, try `float32`: many games store resources as floating-point numbers.
For float values that show decimals, use a small tolerance (for example `0.5`).

## Unknown value

When the number is not shown exactly (an internal timer, a cooldown):

1. **Take snapshot**, let it change, **Take snapshot** again.
2. With no candidates yet, choose a type and **changed** / **increased** / **decreased**,
   **Apply**. This compares the two newest snapshots.
3. Keep taking snapshots and applying **unchanged** / **increased** / ... to narrow down.

## What a result means and what it does not

- A surviving address is a *candidate*, not a validated game value. Copies (UI caches,
  statistics) can follow the real value; the synthetic target's `display_*` fields reproduce
  this. Validation across independent experiments is milestone M3.
- Addresses change every time the game starts. A candidate from yesterday means nothing
  today; M3/M4 will look for stable ways to find the value again.
- Snapshot size is capped by `sampling.max_snapshot_bytes` (1 GiB by default). The timeline
  says when a snapshot was truncated. Raise the cap in a config file if needed.

## Practising without the game

```powershell
python -m aoe2mr.synthetic.target          # prints pid and address
aoe2mr-gui --pid <pid>                     # or "Attach" in the Process Monitor tab
```

Then type `add wood 25`, `tick`, `set gold 500` into the target's console between snapshots.
