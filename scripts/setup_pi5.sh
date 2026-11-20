#!/bin/bash
# ====================================================================
# SCRIPT CÀI ĐẶT TỰ ĐỘNG CHO RASPBERRY PI 5 (1-CLICK SETUP)
# Đề tài: Hệ thống phát hiện bất thường lưu lượng IoT (6 ESP32-S3 + Pi 5)
# ====================================================================

set -e

echo "=== [1/4] Cập nhật hệ thống Raspberry Pi 5 ==="
sudo apt-get update -y

echo "=== [2/4] Cài đặt Mosquitto MQTT Broker & TShark ==="
# Cấu hình cài đặt tshark không hỏi prompt cấp quyền non-root
echo "wireshark-common wireshark-common/install-setuid boolean true" | sudo debconf-set-selections
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y mosquitto mosquitto-clients tshark wireshark

# Cấp quyền cho user hiện tại chạy tshark không cần sudo
sudo usermod -a -G wireshark $USER || true

# Cấu hình Mosquitto cho phép kết nối trong mạng LAN (không cần auth hoặc có auth mở rộng)
cat << 'EOF' | sudo tee /etc/mosquitto/conf.d/iot_lab.conf
listener 1883 0.0.0.0
allow_anonymous true
EOF

echo "=== [3/4] Khởi động Mosquitto Broker ==="
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto

echo "=== [4/4] Cài đặt các thư viện Python cần thiết ==="
sudo apt-get install -y python3-pip python3-venv

# Cài đặt các package cần thiết
pip install --break-system-packages fastapi uvicorn paho-mqtt scikit-learn pandas numpy joblib psutil websockets requests || pip install fastapi uvicorn paho-mqtt scikit-learn pandas numpy joblib psutil websockets requests

echo ""
echo "=========================================================="
echo "  CÀI ĐẶT THÀNH CÔNG TRÊN RASPBERRY PI 5!"
echo "  Địa chỉ IP của Pi 5 trong mạng:"
hostname -I | awk '{print "  -> IP: " $1}'
echo "  Mosquitto Broker đang lắng nghe tại cổng 1883"
echo "=========================================================="

