@echo off
set "KIT=%~dp0.."
set "PYTHONPATH=%KIT%;%PYTHONPATH%"
if defined SDLC_PYTHON ( "%SDLC_PYTHON%" -m sdlc %* ) else ( python -m sdlc %* )
