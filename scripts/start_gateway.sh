#!/bin/bash
# Khởi chạy hệ thống Gateway IoT trên Raspberry Pi 5
cd /home/pi/AIoT
export PATH=/home/pi/.local/bin:$PATH

echo "=== Khởi động Live Feature Pipeline ==="
pkill -f "pipeline/feature_extractor.py" || true
pkill -f "uvicorn backend.app.main:app" || true
sleep 1

nohup python3 pipeline/feature_extractor.py > /home/pi/AIoT/pipeline.log 2>&1 &
echo "Pipeline PID: $!"

echo "=== Khởi động FastAPI Backend & Web Dashboard ==="
nohup python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 > /home/pi/AIoT/backend.log 2>&1 &
echo "Backend PID: $!"

echo "=== Hệ thống Gateway đang chạy tại http://0.0.0.0:8000 ==="
