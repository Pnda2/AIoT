"""
HỆ THỐNG MÔ PHỎNG TOÀN DIỆN LOCAL (KHÔNG CẦN RASPBERRY PI HAY ESP32)
Tự động kích hoạt:
1. MQTT Broker (Mosquitto 127.0.0.1:1883)
2. FastAPI Gateway Backend (127.0.0.1:8000)
3. Live Feature Extraction Pipeline (14 đặc trưng 5s + AI Isolation Forest + RF)
4. Virtual ESP32 Simulator (Giả lập cả 6 node esp32_01 -> esp32_06 với 7 kịch bản)
5. Tự động mở trình duyệt truy cập Dashboard: http://127.0.0.1:8000
"""

import os
import sys
import time
import socket
import subprocess
import webbrowser
import signal

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MOSQUITTO_EXE = r"C:\Program Files\mosquitto\mosquitto.exe"
MOSQUITTO_CONF = os.path.join(PROJECT_ROOT, "data", "mosquitto_local.conf")

processes = []

def is_port_open(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0

def cleanup(sig=None, frame=None):
    print("\n[HỆ THỐNG] Đang dừng tất cả các tiến trình mô phỏng...")
    for name, p in reversed(processes):
        try:
            print(f"  -> Dừng {name} (PID: {p.pid})...")
            p.terminate()
            p.wait(timeout=2)
        except Exception:
            try:
                p.kill()
            except Exception:
                pass
    print("[HỆ THỐNG] Đã dừng toàn bộ an toàn. Tạm biệt!")
    sys.exit(0)

signal.signal(signal.SIGINT, cleanup)
signal.signal(signal.SIGTERM, cleanup)

def main():
    print("=" * 65)
    print("   KHỞI CHẠY MÔ PHỎNG HỆ THỐNG AIoT ANOMALY DETECTION LOCAL")
    print("   (Không cần Raspberry Pi 5 và ESP32 phần cứng)")
    print("=" * 65)

    # 1. Kiểm tra / Khởi động Mosquitto Broker
    if is_port_open(1883):
        print("[1/4] MQTT Broker: Đang hoạt động sẵn trên port 1883.")
    else:
        if os.path.exists(MOSQUITTO_EXE):
            print(f"[1/4] MQTT Broker: Đang khởi động Mosquitto từ {MOSQUITTO_EXE}...")
            cmd = [MOSQUITTO_EXE, "-c", MOSQUITTO_CONF]
            p_mqtt = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            processes.append(("Mosquitto MQTT Broker", p_mqtt))
            time.sleep(1)
            if is_port_open(1883):
                print("      MQTT Broker khởi động thành công (port 1883).")
            else:
                print("      Cảnh báo: Chưa kết nối được port 1883, tiếp tục kiểm tra...")
        else:
            print(f"[1/4] CẢNH BÁO: Không tìm thấy Mosquitto tại {MOSQUITTO_EXE}!")
            print("      Vui lòng cài đặt Mosquitto hoặc bật dịch vụ Mosquitto.")

    # 2. Khởi động FastAPI Backend
    print("[2/4] Web API Backend: Đang khởi động Uvicorn trên port 8000...")
    cmd_backend = [
        sys.executable, "-m", "uvicorn", "backend.app.main:app",
        "--host", "127.0.0.1", "--port", "8000"
    ]
    p_backend = subprocess.Popen(cmd_backend, cwd=PROJECT_ROOT)
    processes.append(("FastAPI Backend", p_backend))
    time.sleep(1.5)

    # 3. Khởi động Pipeline Trích xuất 14 đặc trưng 5s + AI Suy luận
    print("[3/4] Live Pipeline: Đang khởi động trích xuất đặc trưng & AI...")
    cmd_pipe = [sys.executable, os.path.join(PROJECT_ROOT, "pipeline", "feature_extractor.py")]
    p_pipe = subprocess.Popen(cmd_pipe, cwd=PROJECT_ROOT)
    processes.append(("Feature Extraction Pipeline", p_pipe))
    time.sleep(1.0)

    # 4. Khởi động Giả lập 6 Node ESP32
    print("[4/4] Node Simulator: Đang khởi động giả lập 6 node (esp32_01 -> esp32_06)...")
    cmd_sim = [sys.executable, os.path.join(PROJECT_ROOT, "simulator", "virtual_nodes.py")]
    p_sim = subprocess.Popen(cmd_sim, cwd=PROJECT_ROOT)
    processes.append(("Virtual Nodes Simulator", p_sim))
    time.sleep(1.5)

    print("=" * 65)
    print("   TẤT CẢ 4 THÀNH PHẦN ĐÃ HOẠT ĐỘNG HOÀN TOÀN TRÊN MÁY TÍNH!")
    print("   -> Dashboard: http://127.0.0.1:8000")
    print("   -> Bấm Ctrl+C trong cửa sổ này để tắt toàn bộ hệ thống.")
    print("=" * 65)

    # Tự động mở trình duyệt
    try:
        webbrowser.open("http://127.0.0.1:8000")
    except Exception:
        pass

    # Giám sát các tiến trình
    try:
        while True:
            for name, p in processes:
                if p.poll() is not None:
                    print(f"[CẢNH BÁO] Tiến trình {name} đã dừng bất ngờ (exit code: {p.returncode})!")
            time.sleep(2)
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
