import time
import json
import os
import signal
import threading
from datetime import datetime
import numpy as np
import paho.mqtt.client as mqtt
from sklearn.ensemble import IsolationForest
import joblib

import sys
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
from backend.app.db.database import get_db_connection, init_db, prune_old_records
from pipeline.tshark_collector import TsharkCollector
from pipeline.window_features import FEATURE_COLUMNS_14, compute_window_features_14

# Danh sách 6 node
DEVICE_KEYS = [f"esp32_{i:02d}" for i in range(1, 7)]

class LiveFeaturePipeline:
    def __init__(self, broker_host="127.0.0.1", broker_port=1883, window_size=5.0):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.window_size = window_size
        self.running = False
        self.window_seq = 0
        self.tshark = TsharkCollector(interface="wlan0", bpf_filter="port 1883")
        
        # Buffer lưu gói tin MQTT cho từng thiết bị trong cửa sổ hiện tại
        self.packet_buffer = {k: [] for k in DEVICE_KEYS}
        self.lock = threading.Lock()
        
        # Mô hình Local cho luồng Live (hỗ trợ cả v1 6-features và v2 14-features Pipeline)
        self.local_model = None
        self.scenario_model = None
        self.model_n_features = 6
        artifacts_dir = os.path.join(BASE_DIR, "models", "artifacts")
        self.model_path = os.path.join(artifacts_dir, "local_iso_forest.joblib")
        self.scenario_model_path = os.path.join(artifacts_dir, "local_rf_scenario.joblib")
        self.init_local_model()
        
        # MQTT Client để bắt lưu lượng
        self.mqtt_client = mqtt.Client(client_id="gateway_feature_pipeline")
        self.mqtt_client.on_connect = self.on_connect
        self.mqtt_client.on_message = self.on_message

    def init_local_model(self):
        """Khởi tạo hoặc nạp Local Isolation Forest (+ Scenario Classifier nếu có)."""
        if os.path.exists(self.model_path):
            try:
                self.local_model = joblib.load(self.model_path)
                self.model_n_features = int(getattr(self.local_model, "n_features_in_", 6))
                if self.model_n_features == 14 and os.path.exists(self.scenario_model_path):
                    try:
                        self.scenario_model = joblib.load(self.scenario_model_path)
                    except Exception:
                        self.scenario_model = None
                print(f"[Pipeline] Đã nạp Local Isolation Forest ({self.model_n_features} đặc trưng) thành công.")
                return
            except Exception as e:
                print("[Pipeline] Lỗi nạp model local, sẽ fit lại baseline v1:", e)
                
        # Fit đường cơ sở giả định bình thường (TH0: 2-3 packet/5s, len 100-150 bytes, IAT ~2.0s)
        print("[Pipeline] Đang huấn luyện đường cơ sở Local Isolation Forest (TH0)...")
        np.random.seed(42)
        n_base = 300
        base_packet_count = np.random.poisson(lam=2.5, size=n_base)
        base_packet_count = np.clip(base_packet_count, 1, 4)
        base_bytes = base_packet_count * np.random.normal(120, 15, size=n_base)
        base_mean_len = base_bytes / base_packet_count
        base_mean_iat = np.random.normal(2.0, 0.2, size=n_base)
        base_packet_rate = base_packet_count / 5.0
        base_byte_rate = base_bytes / 5.0
        
        X_base = np.column_stack([
            base_packet_count, base_bytes, base_mean_len, base_mean_iat, base_packet_rate, base_byte_rate
        ])
        
        self.local_model = IsolationForest(n_estimators=100, contamination=0.03, random_state=42)
        self.local_model.fit(X_base)
        os.makedirs(os.path.dirname(self.model_path), exist_ok=True)
        joblib.dump(self.local_model, self.model_path)
        print("[Pipeline] Huấn luyện và lưu Local Isolation Forest thành công!")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            print(f"[Pipeline] Đã kết nối MQTT Broker ({self.broker_host}:{self.broker_port})")
            # Đăng ký nhận mọi telemetry từ tất cả các ESP32
            client.subscribe("wievac/+/telemetry")
            client.subscribe("wievac/+/heartbeat")
        else:
            print(f"[Pipeline] Kết nối MQTT thất bại, mã lỗi: {rc}")

    def on_message(self, client, userdata, msg):
        now = time.time()
        topic = msg.topic
        payload_str = msg.payload.decode("utf-8", errors="ignore")
        payload_size = len(msg.payload) + 40 # Thêm 40 bytes overhead header TCP/IP
        
        parts = topic.split("/")
        if len(parts) >= 2:
            device_key = parts[1]
            if device_key in self.packet_buffer:
                with self.lock:
                    self.packet_buffer[device_key].append({
                        "timestamp": now,
                        "size": payload_size,
                        "payload": payload_str
                    })
                
                # Cập nhật thời điểm last_seen vào database
                self.update_device_seen(device_key, now, payload_str)

    def update_device_seen(self, device_key, last_seen, payload_str):
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            scenario = "TH0_NORMAL"
            try:
                data = json.loads(payload_str)
                if "scenario" in data:
                    scenario = data["scenario"]
            except:
                pass
                
            cursor.execute("""
            UPDATE devices 
            SET last_seen = ?, status = 'online', current_scenario = ?
            WHERE id = ?
            """, (last_seen, scenario, device_key))
            conn.commit()
            conn.close()
        except Exception as e:
            pass

    def compute_window_features(self, packets, duration):
        """Trích xuất 6 đặc trưng thống kê của cửa sổ mạng theo đặc tả"""
        if not packets:
            return {
                "packet_count": 0,
                "total_bytes": 0,
                "mean_packet_len": 0.0,
                "mean_iat": 0.0,
                "packet_rate": 0.0,
                "byte_rate": 0.0
            }
            
        packet_count = len(packets)
        sizes = [p["size"] for p in packets]
        total_bytes = sum(sizes)
        mean_len = float(np.mean(sizes))
        
        # Tính IAT (Inter-Arrival Time)
        timestamps = sorted([p["timestamp"] for p in packets])
        if len(timestamps) > 1:
            iats = np.diff(timestamps)
            mean_iat = float(np.mean(iats))
        else:
            mean_iat = duration # Chỉ 1 gói tin
            
        packet_rate = packet_count / duration
        byte_rate = total_bytes / duration
        
        return {
            "packet_count": packet_count,
            "total_bytes": total_bytes,
            "mean_packet_len": round(mean_len, 2),
            "mean_iat": round(mean_iat, 4),
            "packet_rate": round(packet_rate, 2),
            "byte_rate": round(byte_rate, 2)
        }

    def requeue_packets(self, mqtt_snapshots: dict):
        """Hoàn trả các gói tin vào packet_buffer nếu ghi DB thất bại."""
        if not mqtt_snapshots:
            return
        with self.lock:
            for k, pkts in mqtt_snapshots.items():
                if pkts:
                    existing = self.packet_buffer.get(k, [])
                    self.packet_buffer[k] = pkts + existing

    def process_window(self):
        """Chạy theo chu kỳ 5 giây: gom gói, trích xuất 14 đặc trưng, suy luận & ghi log tường minh."""
        now = time.time()
        ts_start = now - self.window_size
        ts_end = now

        with self.lock:
            mqtt_snapshots = {k: list(self.packet_buffer[k]) for k in DEVICE_KEYS}
            for k in DEVICE_KEYS:
                self.packet_buffer[k].clear()

        wire_snapshots = self.tshark.pop_window_packets()

        conn = None
        try:
            conn = get_db_connection()
            self._execute_window_processing(conn, now, ts_start, ts_end, mqtt_snapshots, wire_snapshots)
            conn.commit()
            self.window_seq += 1
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            self.requeue_packets(mqtt_snapshots)
            self.tshark.requeue_window_packets(wire_snapshots)
            print(f"[Pipeline] Lỗi ghi DB cửa sổ #{self.window_seq + 1}, đã hoàn trả buffer: {e}")
            raise
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    def _execute_window_processing(self, conn, now, ts_start, ts_end, mqtt_snapshots, wire_snapshots):
        cursor = conn.cursor()

        cursor.execute("SELECT id, last_seen, current_scenario, status FROM devices")
        db_devices = {row["id"]: dict(row) for row in cursor.fetchall()}

        schema_tag = "v2_14features" if self.model_n_features == 14 else "v1_6features"
        t0_s = datetime.fromtimestamp(ts_start).strftime("%H:%M:%S")
        t1_s = datetime.fromtimestamp(ts_end).strftime("%H:%M:%S")
        win_logs = []

        for device_key in DEVICE_KEYS:
            mqtt_pkts = mqtt_snapshots.get(device_key, [])
            wire_pkts = wire_snapshots.get(device_key, [])
            dev_info = db_devices.get(device_key, {})
            last_seen = dev_info.get("last_seen", 0)
            is_active_before = last_seen > 0
            was_online = dev_info.get("status") == "online"

            if wire_pkts:
                feat_source = "tshark_wire"
                feat14 = compute_window_features_14(wire_pkts, self.window_size)
            elif mqtt_pkts:
                feat_source = "mqtt_fallback"
                pseudo_wire = [
                    {"ts": p["timestamp"], "len": p["size"], "syn": False, "fin": False, "rst": False}
                    for p in mqtt_pkts
                ]
                feat14 = compute_window_features_14(pseudo_wire, self.window_size)
            else:
                feat_source = "empty"
                feat14 = compute_window_features_14([], self.window_size)

            # Lưu đầy đủ 14 đặc trưng + trường tương thích ngược cho Dashboard cũ
            features = dict(feat14)
            features["total_bytes"] = feat14["byte_count"]
            features["mean_packet_len"] = feat14["len_mean"]
            features["mean_iat"] = round(feat14["iat_mean"] / 1000.0, 4)
            features["feature_source"] = feat_source
            features["scenario_label"] = dev_info.get("current_scenario", "TH0_NORMAL")

            # 1. Lưu vector đặc trưng vào bảng windows
            cursor.execute(
                """
                INSERT INTO windows (ts_start, ts_end, device_key, feature_json, source, created_at)
                VALUES (?, ?, ?, ?, 'live_hardware', ?)
                """,
                (ts_start, ts_end, device_key, json.dumps(features), now),
            )

            # 2. KIỂM TRA QUY TẮC WATCHDOG TIMEOUT (TH4 - Silence / Mất Heartbeat)
            if is_active_before and features["packet_count"] == 0 and (now - last_seen > 8.0):
                cursor.execute("UPDATE devices SET status = 'offline' WHERE id = ?", (device_key,))
                if was_online:
                    cursor.execute(
                        """
                        INSERT INTO alerts (created_at, device_key, score, predicted_label, severity, model_version, alert_type, reason_json)
                        VALUES (?, ?, 1.0, 'SILENCE_TIMEOUT', 'WARNING', 'WatchdogRule_v1', 'rule', ?)
                        """,
                        (
                            now,
                            device_key,
                            json.dumps(
                                {
                                    "rule": "Watchdog Timeout (>8s không nhận được telemetry)",
                                    "last_seen_sec_ago": round(now - last_seen, 1),
                                    "action": "Kiểm tra nguồn hoặc kết nối Wi-Fi của thiết bị",
                                }
                            ),
                        ),
                    )
                    win_logs.append(f"  └── {device_key} | pkt=0 | is_empty=1 | Watchdog=SILENCE_TIMEOUT (>8s)")
                continue

            # 3. SUY LUẬN AI (LOCAL ISOLATION FOREST v1 hoặc v2 14-đặc-trưng)
            if features["packet_count"] > 0:
                if self.model_n_features == 14:
                    vector = np.array([[features[c] for c in FEATURE_COLUMNS_14]], dtype=float)
                else:
                    feat6 = self.compute_window_features(mqtt_pkts if mqtt_pkts else wire_pkts, self.window_size) if mqtt_pkts else {
                        "packet_count": feat14["packet_count"],
                        "total_bytes": feat14["byte_count"],
                        "mean_packet_len": feat14["len_mean"],
                        "mean_iat": feat14["iat_mean"] / 1000.0,
                        "packet_rate": feat14["packet_rate"],
                        "byte_rate": feat14["byte_rate"],
                    }
                    vector = np.array(
                        [[
                            feat6["packet_count"],
                            feat6["total_bytes"],
                            feat6["mean_packet_len"],
                            feat6["mean_iat"],
                            feat6["packet_rate"],
                            feat6["byte_rate"],
                        ]],
                        dtype=float,
                    )

                pred = int(self.local_model.predict(vector)[0])
                score = float(self.local_model.decision_function(vector)[0])
                hard_rule_hit = (
                    features["tcp_rst_count"] >= 3
                    or features["tcp_syn_count"] >= 3
                    or features["tcp_fin_count"] >= 3
                    or features["packet_rate"] >= 8.0
                    or features["len_mean"] >= 700.0
                )

                sc_pred = None
                if self.scenario_model is not None and self.model_n_features == 14:
                    try:
                        sc_pred = str(self.scenario_model.predict(vector)[0])
                    except Exception:
                        pass

                # Điều kiện kích hoạt cảnh báo thực sự:
                # 1. Vi phạm luật cứng mạng (bắn gói vọt, payload lớn, ngắt nối TCP dồn dập)
                # 2. Hoặc mô hình ScenarioClassifier chỉ đích danh kịch bản tấn công (TH1..TH6)
                # 3. Hoặc Isolation Forest lệch sâu hẳn khỏi phân phối (score <= -0.04)
                # (Nếu sc_pred là 'normal' và score > -0.04 mấp mé sát 0 thì coi là biến thiên ngẫu nhiên bình thường, không báo động giả)
                is_real_anomaly = hard_rule_hit or (sc_pred is not None and sc_pred != "normal") or score <= -0.04

                if is_real_anomaly and (pred == -1 or hard_rule_hit or (sc_pred is not None and sc_pred != "normal")):
                    anomaly_type = "UNKNOWN_ANOMALY"
                    reasons = []

                    sc_pred_vn = {
                        "normal": "Bình thường",
                        "high_rate": "Gói cao",
                        "large_payload": "Gói lớn",
                        "reconnect": "Tái kết nối",
                        "silence": "Mất kết nối",
                        "burst": "Xả burst",
                        "auth_fail": "Lỗi xác thực",
                    }.get(sc_pred, sc_pred)

                    if features["tcp_rst_count"] >= 2:
                        anomaly_type = "TH6_AUTH_FAIL"
                        reasons.append(f"Cờ TCP RST tăng cao ({features['tcp_rst_count']} RST/5s — nghi từ chối xác thực)")
                    elif features["tcp_syn_count"] >= 2 or features["tcp_fin_count"] >= 2:
                        anomaly_type = "TH3_RECONNECT"
                        reasons.append(
                            f"Chu kỳ kết nối lại bất thường (SYN={features['tcp_syn_count']}, FIN={features['tcp_fin_count']})"
                        )
                    elif features["packet_rate"] >= 8.0:
                        anomaly_type = "TH1_HIGH_RATE"
                        reasons.append(f"Tốc độ gói tin tăng vọt: {features['packet_rate']} pkt/s (Chuẩn: ~0.5 pkt/s)")
                    elif features["len_mean"] >= 700.0:
                        anomaly_type = "TH2_LARGE_PAYLOAD"
                        reasons.append(f"Kích thước gói bất thường: {features['len_mean']} bytes (Chuẩn: ~120B)")
                    elif features["iat_mean"] < 200.0 and features["packet_count"] >= 4:
                        anomaly_type = "TH5_BURST_TRAFFIC"
                        reasons.append(f"Khoảng cách giữa các gói dồn dập (IAT={features['iat_mean']}ms)")
                    elif sc_pred is not None and sc_pred != "normal":
                        anomaly_type = f"TH_{sc_pred.upper()}"
                        reasons.append(f"Bộ phân loại kịch bản phát hiện: {sc_pred_vn}")
                    else:
                        anomaly_type = "TRAFFIC_ANOMALY"
                        reasons.append(f"Lệch khỏi phân phối đường cơ sở (Score: {score:.3f})")

                    if sc_pred is not None:
                        reasons.append(f"Bộ phân loại kịch bản dự đoán: {sc_pred_vn}")

                    alert_src = "ml" if pred == -1 else "rule"
                    model_tag = f"LocalIsolationForest_{schema_tag}" if pred == -1 else f"HybridNetworkRule_{schema_tag}"
                    cursor.execute(
                        """
                        INSERT INTO alerts (created_at, device_key, score, predicted_label, severity, model_version, alert_type, reason_json)
                        VALUES (?, ?, ?, ?, 'CRITICAL', ?, ?, ?)
                        """,
                        (
                            now,
                            device_key,
                            round(score, 4),
                            anomaly_type,
                            model_tag,
                            alert_src,
                            json.dumps({"anomaly_score": round(score, 4), "features": features, "reasons": reasons}),
                        ),
                    )
                    verdict_str = f"ANOMALY ({score:+.3f} -> {anomaly_type})"
                else:
                    verdict_str = f"NORMAL ({score:+.3f})"

                win_logs.append(
                    f"  ├── {device_key} | pkt={features['packet_count']} | {features['byte_count']}B | "
                    f"rate={features['packet_rate']:.2f}/s | len={features['len_mean']:.0f}B | iat={features['iat_mean']:.0f}ms | "
                    f"S/F/R={features['tcp_syn_count']}/{features['tcp_fin_count']}/{features['tcp_rst_count']} | {verdict_str} [{feat_source}]"
                )

        if win_logs:
            header = f"[WINDOW #{self.window_seq} | {t0_s} -> {t1_s}] ({schema_tag} | Active={len(win_logs)}/6)"
            full_msg = header + "\n" + "\n".join(win_logs)
            print(full_msg)
            lvl = "WARNING" if any("ANOMALY" in l or "TIMEOUT" in l for l in win_logs) else "INFO"
            cursor.execute(
                """
                INSERT INTO system_events (ts, component, level, message, correlation_id)
                VALUES (?, 'window_extractor', ?, ?, ?)
                """,
                (now, lvl, full_msg, f"win_{self.window_seq}"),
            )
            cursor.execute(
                """
                DELETE FROM system_events WHERE component = 'window_extractor' AND id NOT IN (
                    SELECT id FROM system_events WHERE component = 'window_extractor' ORDER BY id DESC LIMIT 120
                )
                """
            )

    def run_loop(self):
        """Vòng lặp chạy ngầm mỗi 5 giây"""
        self.running = True
        print(f"[Pipeline] Bắt đầu vòng lặp giám sát cửa sổ {self.window_size}s...")
        while self.running:
            time.sleep(self.window_size)
            try:
                self.process_window()
                # Tự động dọn dẹp giữ tối đa 10,000 cửa sổ mỗi 60 chu kỳ (~5 phút)
                if self.window_seq % 60 == 0:
                    prune_old_records(max_windows=10000, max_packets=5000)
            except Exception as e:
                print("[Pipeline] Lỗi xử lý cửa sổ:", e)

    def start(self):
        try:
            init_db()
            self.tshark.start()
            self.mqtt_client.connect(self.broker_host, self.broker_port, 60)
            self.mqtt_client.loop_start()
            t = threading.Thread(target=self.run_loop, daemon=True)
            t.start()
            print("[Pipeline] Live Feature Pipeline đã khởi chạy thành công.")
        except Exception as e:
            print("[Pipeline] Lỗi khởi động kết nối MQTT:", e)

if __name__ == "__main__":
    pipeline = LiveFeaturePipeline(broker_host="127.0.0.1", broker_port=1883)

    def handle_sigterm(signum, frame):
        pipeline.running = False
        pipeline.tshark.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_sigterm)
    pipeline.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pipeline.running = False
        pipeline.tshark.stop()
        print("Dừng pipeline.")

