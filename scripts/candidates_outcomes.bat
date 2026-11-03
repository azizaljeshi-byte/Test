@echo off
cd /d "%~dp0.."
python scripts\candidates_outcomes.py > data\candidates_outcomes.txt 2>&1
type data\candidates_outcomes.txt
pause
