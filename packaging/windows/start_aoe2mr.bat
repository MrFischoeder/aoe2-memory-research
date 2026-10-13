@echo off
rem Starts the AoE2 Memory Research window (read-only). It attaches automatically when
rem Age of Empires II: DE is running and waits for it otherwise.
start "" "%~dp0AoE2MemoryResearch\AoE2MemoryResearch.exe" %*
