@echo off
cd /d "%~dp0.."
python scripts\ema_pullback_test.py > data\ema_pullback_test.txt 2>&1
type data\ema_pullback_test.txt
pause
