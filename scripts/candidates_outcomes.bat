@echo off
cd /d "%~dp0.."
if not exist data mkdir data
".venv\Scripts\python.exe" scripts\candidates_outcomes.py > data\candidates_outcomes.txt 2>&1
