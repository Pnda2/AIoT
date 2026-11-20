#!/bin/bash
set -e

cat > /etc/systemd/system/iot_pipeline.service << 'EOF'
[Unit]
Description=IoT Live Feature Extraction & Anomaly Pipeline
After=network.target mosquitto.service
Requires=mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/AIoT
Environment="PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 -u /home/pi/AIoT/pipeline/feature_extractor.py
Restart=always
RestartSec=5
StandardOutput=append:/home/pi/AIoT/pipeline.log
StandardError=append:/home/pi/AIoT/pipeline.log

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/systemd/system/iot_gateway.service << 'EOF'
[Unit]
Description=IoT Traffic Anomaly Detection Gateway
After=network.target mosquitto.service iot_pipeline.service
Requires=mosquitto.service

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/AIoT
Environment="PATH=/home/pi/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/usr/bin/python3 -m uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5
StandardOutput=append:/home/pi/AIoT/backend.log
StandardError=append:/home/pi/AIoT/backend.log

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable iot_pipeline iot_gateway
systemctl restart iot_pipeline iot_gateway
sleep 2
systemctl status iot_pipeline iot_gateway --no-pager

