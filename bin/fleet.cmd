@echo off
rem SPEC §14 portability: %~dp0 is this .cmd file's own directory (with a
rem trailing backslash), so this shim finds fleet.py wherever the repo is
rem actually cloned -- no hardcoded C:\proga\claude-fleet literal here.
py -3.13 "%~dp0fleet.py" %*
