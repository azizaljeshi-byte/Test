@echo off
cd /d "%~dp0.."
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% scripts\ema_pullback_test.py > data\ema_pullback_test.txt 2>&1
type data\ema_pullback_test.txt
pause
