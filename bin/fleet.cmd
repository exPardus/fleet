@echo off
rem SPEC §14 portability: %~dp0 is this .cmd file's own directory (with a
rem trailing backslash), so this shim finds fleet.py wherever the repo is
rem actually cloned -- no hardcoded C:\proga\claude-fleet literal here.
rem
rem P1-9 (ULTRAREVIEW 2026-07-30), the same defect one level up: cmd.exe
rem resolves a bare command out of the CURRENT DIRECTORY before PATH, so a
rem planted `py.cmd` hijacks the entire CLI before Python ever starts --
rem measured: from a directory holding `@echo HIJACKED`, `py -3.13 ...` ran the
rem plant. This variable is cmd.exe's documented opt-out; with it set the same
rem line resolves the real launcher off PATH. It is set BEFORE the `py` line
rem for that reason, and deliberately left in the environment fleet.py and its
rem workers inherit: on Python >= 3.12 it also makes `shutil.which` skip the
rem curdir insert (`resolve_claude_executable` refuses that resolution outright,
rem because on the 3.10 floor the insert is unconditional and no variable
rem suppresses it).
set "NoDefaultCurrentDirectoryInExePath=1"
py -3.13 "%~dp0fleet.py" %*
