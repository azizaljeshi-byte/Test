@echo off
cd /d "%~dp0.."
.venv\Scripts\python.exe -W ignore scripts\stab_study.py > data\stab_study.txt 2>&1
type data\stab_study.txt
pause
