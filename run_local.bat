@echo off
title IoT Anomaly Detection - Local Simulation
cd /d "%~dp0"
python scripts\run_local.py
if errorlevel 1 pause
