AoE2 Memory Research - Windows package
=====================================

Start AoE2 Memory Research:   double-click start_aoe2mr.bat
Start the game and the tool:  double-click start_game_and_aoe2mr.bat

The window waits for AoE2DE_s.exe and attaches automatically (read-only).
Then, in the "Memory Research" tab:
  1. Take snapshot
  2. Type: int32 (or float32), Filter: "equals value", Value: e.g. your wood, Apply
  3. Change the value in game (gather wood), Take snapshot again
  4. Filter "increased by value" (or "changed"), Apply, repeat until few candidates remain
  5. Tick "Live values" to watch candidates update

Rules: single-player only, read-only, no memory writes, no input automation.
Do not run the game or this tool as administrator.

Results and logs are saved in the research_data folder next to the program.
Windows SmartScreen may warn about an unsigned program: "More info" -> "Run anyway".
No Python installation is needed.
