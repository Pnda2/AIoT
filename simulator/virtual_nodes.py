"""
TRÌNH MÔ PHỎNG HYBRID CHO CÁC NODE ESP32 CÒN LẠI (ESP32_02 ĐẾN ESP32_06)
Giúp hiển thị đầy đủ cả 6 node trên Dashboard ngay cả khi chưa kịp nạp code hết 6 board vật lý.
Khi có board vật lý thật cắm vào, board thật sẽ tự động gửi đè lên cùng topic MQTT.
"""

import os
import time
import json
import random
import threading
import paho.mqtt.client as mqtt

BROKER_HOST = os.getenv("MQTT_BROKER", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_PORT", "1883"))

NODES_CONFIG = {
    "esp32_01": {"id": 1, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
    "esp32_02": {"id": 2, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
    "esp32_03": {"id": 3, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
    "esp32_04": {"id": 4, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
    "esp32_05": {"id": 5, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
    "esp32_06": {"id": 6, "scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False},
}

DUMMY_PADDING = "A" * 1400

class SimulatedNode(threading.Thread):
    def __init__(self, dev_key, cfg):
        super().__init__(daemon=True)
        self.dev_key = dev_key
        self.cfg = cfg
        self.running = True
        self.seq = 0
        self.client = mqtt.Client(client_id=f"sim_{dev_key}")
        self.client.on_message = self.on_cmd
        self.telemetry_topic = f"wievac/{dev_key}/telemetry"
        self.control_topic = f"wievac/control/{dev_key}"
        self.heartbeat_topic = f"wievac/{dev_key}/heartbeat"

    def on_cmd(self, client, userdata, msg):
        cmd = msg.payload.decode("utf-8").strip()
        print(f"[{self.dev_key}] Nhận lệnh điều khiển: {cmd}")
        if "TH0" in cmd:
            self.cfg.update({"scenario": "TH0_NORMAL", "rate_hz": 0.8, "large": False, "burst": False, "reconnect": False})
        elif "TH1" in cmd:
            self.cfg.update({"scenario": "TH1_HIGH_RATE", "rate_hz": 15.0, "large": False, "burst": False, "reconnect": False})
        elif "TH2" in cmd:
            self.cfg.update({"scenario": "TH2_LARGE_PAYLOAD", "rate_hz": 0.5, "large": True, "burst": False, "reconnect": False})
        elif "TH3" in cmd:
            self.cfg.update({"scenario": "TH3_RECONNECT", "rate_hz": 0.33, "large": False, "burst": False, "reconnect": True})
        elif "TH4" in cmd:
            self.cfg.update({"scenario": "TH4_SILENCE", "rate_hz": 0.0, "large": False, "burst": False, "reconnect": False})
        elif "TH5" in cmd:
            self.cfg.update({"scenario": "TH5_BURST", "rate_hz": 1.0, "large": False, "burst": True, "reconnect": False})
        elif "TH6" in cmd:
            self.cfg.update({"scenario": "TH6_AUTH_FAIL", "rate_hz": 2.0, "large": False, "burst": False, "reconnect": False})

    def run(self):
        try:
            self.client.connect(BROKER_HOST, BROKER_PORT, 60)
            self.client.subscribe(self.control_topic)
            self.client.subscribe("wievac/control/all")
            self.client.publish(self.heartbeat_topic, "online")
            self.client.loop_start()
            print(f"[{self.dev_key}] Khởi chạy node giả lập thành công.")
        except Exception as e:
            print(f"[{self.dev_key}] Lỗi kết nối MQTT:", e)
            return

        burst_count = 0
        while self.running:
            sc = self.cfg.get("scenario", "TH0_NORMAL")
            
            if sc == "TH4_SILENCE":
                time.sleep(1)
                continue
                
            self.seq += 1
            temp = 25.0 + random.uniform(0, 10)
            hum = 60.0 + random.uniform(0, 15)
            
            payload = {
                "id": self.dev_key,
                "seq": self.seq,
                "uptime": int(time.time()),
                "temp": round(temp, 2),
                "hum": round(hum, 2),
                "scenario": sc
            }
            if self.cfg.get("large"):
                payload["padding"] = DUMMY_PADDING

            if self.cfg.get("burst"):
                for _ in range(15):
                    self.seq += 1
                    payload["seq"] = self.seq
                    try:
                        self.client.publish(self.telemetry_topic, json.dumps(payload))
                    except Exception:
                        pass
                    time.sleep(0.04)
                time.sleep(4.0)
                continue

            try:
                self.client.publish(self.telemetry_topic, json.dumps(payload))
            except Exception as e:
                pass

            if self.cfg.get("reconnect"):
                time.sleep(2)
                try: self.client.disconnect()
                except Exception: pass
                time.sleep(1)
                try:
                    self.client.connect(BROKER_HOST, BROKER_PORT, 60)
                    self.client.loop_start()
                except Exception: pass
                continue

            rate = self.cfg.get("rate_hz", 0.8)
            if rate > 0:
                sleep_sec = (1.0 / rate) + random.uniform(-0.12, 0.12)
                time.sleep(max(0.05, sleep_sec))
            else:
                time.sleep(1.0)

def start_simulators():
    threads = []
    print("=== Khởi động 6 node ESP32 giả lập (esp32_01 -> esp32_06) ===")
    for k, cfg in NODES_CONFIG.items():
        t = SimulatedNode(k, cfg)
        t.start()
        threads.append(t)
    print("Đang chạy 6 node giả lập kết nối MQTT. Nhấn Ctrl+C để dừng.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Dừng các node mô phỏng.")

if __name__ == "__main__":
    start_simulators()

