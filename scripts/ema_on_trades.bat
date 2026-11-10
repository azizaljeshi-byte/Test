@echo off
cd /d "%~dp0.."
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% scripts\ema_on_trades.py > data\ema_on_trades.txt 2>&1
type data\ema_on_trades.txt | findstr /v /c:"Warning" /c:"inplace" /c:"See https" /c:"  quotes" /c:"  dividends" /c:"  df." /c:"  data."
pause
