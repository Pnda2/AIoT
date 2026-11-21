import os
import time
import json
import shutil
import sqlite3
import subprocess
import threading
from collections import deque

import sys
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from backend.app.db.database import get_db_connection

MQTT_TYPES = {
    "1": "CONNECT",
    "2": "CONNACK",
    "3": "PUBLISH",
    "4": "PUBACK",
    "8": "SUBSCRIBE",
    "9": "SUBACK",
    "10": "UNSUBSCRIBE",
    "12": "PINGREQ",
    "13": "PINGRESP",
    "14": "DISCONNECT",
}

MAX_PACKET_LOGS = 300
MAX_OBSERVATION_PACKETS = 50000


class TsharkCollector:
    """Thu thập lưu lượng mạng thật bằng dumpcap + tshark (lưu .pcapng xoay vòng và phân tích gói TCP/MQTT)."""

    def __init__(self, interface="wlan0", bpf_filter="port 1883", capture_dir=None):
        self.interface = interface
        self.bpf_filter = bpf_filter
        if capture_dir is None:
            capture_dir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), "..", "data", "local_captures")
            )
        self.capture_dir = capture_dir
        os.makedirs(self.capture_dir, exist_ok=True)

        self.running = False
        self.lock = threading.Lock()
        self.packet_buffer = []
        self.observation_buffer = []
        self.window_packets = {}    # device_key -> list of {ts, len, syn, fin, rst} cho 14 đặc trưng 5s
        self.pending_alerts = []
        self.ip_to_device = {}
        self.pending_ip_updates = {}
        self.connect_history = {}   # device_key -> deque of timestamps
        self.alert_cooldown = {}    # (device_key, label) -> last_alert_ts

        self._procs = []
        self._preload_known_ips()

    def _preload_known_ips(self):
        try:
            conn = get_db_connection()
            rows = conn.execute("SELECT id AS device_key, ip_address FROM devices WHERE ip_address IS NOT NULL AND ip_address != ''").fetchall()
            conn.close()
            for r in rows:
                ip = r["ip_address"]
                if ip and ip not in ("0.0.0.0", "127.0.0.1"):
                    self.ip_to_device[ip] = r["device_key"]
        except Exception:
            pass

    def is_available(self):
        return bool(shutil.which("dumpcap") and shutil.which("tshark"))

    def _resolve_device_key(self, src_ip, dst_ip, src_port, topic, client_id):
        # Xác định đâu là IP của thiết bị IoT (port khác 1883), tránh nhận nhầm IP Broker (port 1883)
        esp_ip = dst_ip if src_port == "1883" else src_ip

        if client_id and client_id.startswith("esp32_"):
            dev = client_id.strip()
            if esp_ip:
                self._bind_ip(esp_ip, dev)
            return dev

        if topic:
            parts = topic.split("/")
            for part in parts:
                if part.startswith("esp32_"):
                    if esp_ip and esp_ip != "127.0.0.1":
                        self._bind_ip(esp_ip, part)
                    return part

        if src_ip in self.ip_to_device:
            return self.ip_to_device[src_ip]
        if dst_ip in self.ip_to_device:
            return self.ip_to_device[dst_ip]
        return None

    def _bind_ip(self, ip, device_key):
        if self.ip_to_device.get(ip) != device_key:
            self.ip_to_device[ip] = device_key
            self.pending_ip_updates[device_key] = ip

    def _emit_alert_once(self, device_key, label, severity, details, cooldown=15.0):
        now = time.time()
        key = (device_key, label)
        if now - self.alert_cooldown.get(key, 0) < cooldown:
            return
        self.alert_cooldown[key] = now
        self.pending_alerts.append((now, device_key, 1.0, label, severity, "TsharkNetworkRule_v1", "tshark", json.dumps(details)))

    def _run_pcap_ring(self):
        """Ghi file .pcapng xoay vòng (tối đa 5 file x 512KB = 2.5MB) để mở bằng Wireshark."""
        out_path = os.path.join(self.capture_dir, "mqtt_lab.pcapng")
        cmd = [
            "dumpcap", "-q", "-i", self.interface,
            "-f", self.bpf_filter,
            "-b", "filesize:512", "-b", "files:5",
            "-w", out_path,
        ]
        while self.running:
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._procs.append(proc)
                proc.wait()
            except Exception as e:
                print(f"[Tshark] Lỗi dumpcap ring-buffer: {e}")
            if self.running:
                time.sleep(3)

    def _run_live_dissector(self):
        """Pipe dumpcap -> tshark -r - để đọc trường gói tin realtime mà không tạo file rác ở /tmp."""
        cap_cmd = ["dumpcap", "-q", "-i", self.interface, "-f", self.bpf_filter, "-w", "-"]
        dissect_cmd = [
            "tshark", "-l", "-n", "-r", "-",
            "-T", "fields", "-E", "separator=|",
            "-e", "frame.time_epoch",
            "-e", "ip.src",
            "-e", "ip.dst",
            "-e", "tcp.srcport",
            "-e", "frame.len",
            "-e", "tcp.flags.str",
            "-e", "mqtt.msgtype",
            "-e", "mqtt.topic",
            "-e", "mqtt.clientid",
            "-e", "mqtt.conack.val",
        ]
        while self.running:
            cap_proc = None
            tshark_proc = None
            try:
                cap_proc = subprocess.Popen(cap_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                tshark_proc = subprocess.Popen(
                    dissect_cmd,
                    stdin=cap_proc.stdout,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
                cap_proc.stdout.close()
                self._procs.extend([cap_proc, tshark_proc])

                for line in tshark_proc.stdout:
                    if not self.running:
                        break
                    self._handle_line(line)
            except Exception as e:
                print(f"[Tshark] Lỗi đọc luồng tshark: {e}")
            finally:
                for p in (tshark_proc, cap_proc):
                    if p and p.poll() is None:
                        try:
                            p.terminate()
                        except Exception:
                            pass
            if self.running:
                time.sleep(2)

    def _handle_line(self, line):
        raw = line.rstrip("\r\n")
        if not raw:
            return
        parts = raw.split("|")
        while len(parts) < 10:
            parts.append("")

        ts_str, src_ip, dst_ip, src_port, len_str, flags_raw, msgtype_raw, topic_raw, client_raw, conack_raw = parts[:10]
        try:
            ts = float(ts_str) if ts_str else time.time()
            frame_len = int(len_str) if len_str else 0
        except ValueError:
            return

        flags = "".join(c for c in flags_raw if c.isalpha())
        msg_codes = [c.strip() for c in msgtype_raw.split(",") if c.strip()]
        mqtt_names = [MQTT_TYPES.get(c, f"MQTT_{c}") for c in msg_codes]
        mqtt_label = "+".join(mqtt_names) if mqtt_names else "TCP"

        topic = topic_raw.split(",")[0].strip() if topic_raw else ""
        client_id = client_raw.split(",")[0].strip() if client_raw else ""
        dev_key = self._resolve_device_key(src_ip, dst_ip, src_port.strip(), topic, client_id)

        # Kiểm tra bất thường tầng mạng từ gói tin thật
        if dev_key:
            if "1" in msg_codes:
                hist = self.connect_history.setdefault(dev_key, deque(maxlen=10))
                hist.append(ts)
                recent = [t for t in hist if (ts - t) <= 15.0]
                if len(recent) >= 2:
                    self._emit_alert_once(
                        dev_key,
                        "RECONNECT_STORM",
                        "WARNING",
                        {
                            "rule": f"Tshark phát hiện kết nối lại MQTT liên tục ({len(recent)} lần/15s)",
                            "src_ip": src_ip,
                            "tcp_flags": flags,
                        },
                        cooldown=20.0,
                    )

            if "2" in msg_codes and conack_raw:
                codes = [v.strip() for v in conack_raw.split(",") if v.strip()]
                bad_codes = [v for v in codes if v != "0"]
                if bad_codes:
                    self._emit_alert_once(
                        dev_key,
                        "AUTH_FAILURE",
                        "CRITICAL",
                        {
                            "rule": f"Tshark bắt được MQTT CONNACK từ chối xác thực (code={bad_codes[0]})",
                            "dst_ip": dst_ip,
                        },
                        cooldown=10.0,
                    )

        # Đẩy MỌI gói TCP/MQTT (kể cả bare ACK) vào bộ đệm 5s để tính đúng 14 đặc trưng khớp .pcapng offline
        if dev_key:
            pkt_feat_item = {
                "ts": ts,
                "len": frame_len,
                "syn": ("S" in flags) and ("A" not in flags),
                "fin": ("F" in flags),
                "rst": ("R" in flags),
            }
            with self.lock:
                buf = self.window_packets.setdefault(dev_key, [])
                if len(buf) < 5000:
                    buf.append(pkt_feat_item)

        info = topic or (f"client={client_id}" if client_id else f"TCP [{flags}]")
        if "2" in msg_codes and conack_raw:
            info = f"CONNACK rc={conack_raw}"

        # Giữ bảng gói tóm tắt và cửa sổ quan sát đầy đủ theo hai luồng đọc.
        has_ctrl_flag = any(c in flags for c in ("S", "F", "R"))
        with self.lock:
            packet = (ts, src_ip, dst_ip, frame_len, flags, mqtt_label, dev_key or "-", info)
            if dev_key:
                self.observation_buffer.append(packet)
                if len(self.observation_buffer) > MAX_OBSERVATION_PACKETS:
                    del self.observation_buffer[:MAX_OBSERVATION_PACKETS // 10]
            if msg_codes or has_ctrl_flag:
                self.packet_buffer.append(packet)

    def pop_window_packets(self):
        """Lấy và làm rỗng danh sách gói tin thô theo từng thiết bị cho chu kỳ trích xuất 5s."""
        with self.lock:
            out = {k: list(v) for k, v in self.window_packets.items()}
            self.window_packets.clear()
        return out

    def requeue_window_packets(self, packets_by_device: dict):
        """Hoàn trả lại các gói tin vào window_packets nếu lưu DB thất bại."""
        if not packets_by_device:
            return
        with self.lock:
            for k, pkts in packets_by_device.items():
                if pkts:
                    existing = self.window_packets.get(k, [])
                    self.window_packets[k] = pkts + existing

    def _flush_loop(self):
        cycle = 0
        while self.running:
            time.sleep(2.0)
            self.flush_to_db()
            cycle += 1
            if cycle % 15 == 0:
                self._prune_old_captures(keep=5)

    def flush_to_db(self):
        with self.lock:
            packets = list(self.packet_buffer)
            observations = list(self.observation_buffer)
            alerts = list(self.pending_alerts)
            ip_updates = dict(self.pending_ip_updates)
            self.packet_buffer.clear()
            self.observation_buffer.clear()
            self.pending_alerts.clear()
            self.pending_ip_updates.clear()

        if not packets and not observations and not alerts and not ip_updates:
            return

        conn = None
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            if packets:
                cursor.executemany(
                    """
                    INSERT INTO packet_logs (ts, src_ip, dst_ip, frame_len, tcp_flags, mqtt_type, device_key, info)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    packets,
                )
                cursor.execute(
                    f"""
                    DELETE FROM packet_logs
                    WHERE id <= (SELECT MAX(id) - {MAX_PACKET_LOGS} FROM packet_logs)
                    """
                )

            if observations:
                cursor.executemany(
                    """INSERT INTO observation_packets
                    (ts, src_ip, dst_ip, frame_len, tcp_flags, mqtt_type, device_key, info)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    observations,
                )
                cursor.execute(
                    """DELETE FROM observation_packets
                    WHERE id <= (SELECT MAX(id) - ? FROM observation_packets)""",
                    (MAX_OBSERVATION_PACKETS,),
                )

            for dev_key, ip in ip_updates.items():
                cursor.execute("UPDATE devices SET ip_address = ? WHERE id = ?", (ip, dev_key))

            if alerts:
                cursor.executemany(
                    """
                    INSERT INTO alerts (created_at, device_key, score, predicted_label, severity, model_version, alert_type, reason_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    alerts,
                )

            conn.commit()
            conn.close()
        except Exception as e:
            print(f"[Tshark] Lỗi ghi DB: {e}")
            if conn:
                try:
                    conn.rollback()
                    conn.close()
                except Exception:
                    pass
            # Hoàn trả lại dữ liệu vào hàng đợi nếu ghi DB thất bại (chống mất gói khi DB locked)
            with self.lock:
                self.packet_buffer = (packets + self.packet_buffer)[-MAX_PACKET_LOGS:]
                self.observation_buffer = (observations + self.observation_buffer)[-MAX_OBSERVATION_PACKETS:]
                self.pending_alerts = alerts + self.pending_alerts
                for k, v in ip_updates.items():
                    self.pending_ip_updates.setdefault(k, v)

    def _prune_old_captures(self, keep=5):
        try:
            items = []
            for f in os.listdir(self.capture_dir):
                if f.endswith(".pcapng") or f.endswith(".pcap"):
                    fp = os.path.join(self.capture_dir, f)
                    try:
                        items.append((fp, os.path.getmtime(fp)))
                    except Exception:
                        pass
            items.sort(key=lambda x: x[1], reverse=True)
            for fp, _ in items[keep:]:
                try:
                    os.remove(fp)
                except Exception:
                    pass
        except Exception:
            pass

    def start(self):
        if not self.is_available():
            print("[Tshark] Không tìm thấy dumpcap/tshark trên hệ thống, bỏ qua collector.")
            return False

        self._prune_old_captures(keep=5)
        self.running = True
        threads = [
            threading.Thread(target=self._run_pcap_ring, daemon=True),
            threading.Thread(target=self._run_live_dissector, daemon=True),
            threading.Thread(target=self._flush_loop, daemon=True),
        ]
        for t in threads:
            t.start()
        print(f"[Tshark] Đã bật bắt gói thật trên {self.interface} ({self.bpf_filter}) -> {self.capture_dir}")
        return True

    def stop(self):
        self.running = False
        for p in self._procs:
            if p and p.poll() is None:
                try:
                    p.terminate()
                except Exception:
                    pass
        self.flush_to_db()
