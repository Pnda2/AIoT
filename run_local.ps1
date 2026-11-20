# PowerShell Launcher cho mô phỏng Local
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "   KHỞI CHẠY HỆ THỐNG MÔ PHỎNG ANOMALY DETECTION LOCAL (WINDOWS)    " -ForegroundColor Green
Write-Host "=====================================================================" -ForegroundColor Cyan

python scripts/run_local.py
