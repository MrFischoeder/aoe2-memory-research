@echo off
rem Starts Age of Empires II: DE through Steam, then the research window.
rem The window waits for the game process and attaches when it appears.
rem Use it for single-player games only.
start "" "steam://rungameid/813780"
start "" "%~dp0AoE2MemoryResearch\AoE2MemoryResearch.exe" %*
