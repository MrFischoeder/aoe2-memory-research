AoE2 Memory Research - Windows package
=====================================

Start AoE2 Memory Research:   double-click start_aoe2mr.bat
Start the game and the tool:  double-click start_game_and_aoe2mr.bat

The window waits for AoE2DE_s.exe and attaches automatically (read-only).
Then, in the "Memory Research" tab:
  1. Type: float32, Filter: "value shown in game", Value: the wood number on screen
  2. Press New scan (or Enter) and wait
  3. Change the value in game (gather or spend wood)
  4. Type the new number, press Next scan (or Enter); repeat until few candidates remain
  5. Tick "Live values" to watch candidates update
  If nothing is found, try int32 with "exact value". If the timeline says TRUNCATED,
  raise "Snapshot limit (MiB)" and run New scan again.

Rules: single-player only, read-only, no memory writes, no input automation.
Do not run the game or this tool as administrator.

Results and logs are saved in the research_data folder next to the program.
Windows SmartScreen may warn about an unsigned program: "More info" -> "Run anyway".
No Python installation is needed.
