import sqlite3
import json
import os
import time
from contextlib import closing

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "iot_system.db")

def get_db_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Bảng quản lý thiết bị (6 ESP32-S3)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS devices (
        id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        device_type TEXT NOT NULL,
        pseudonym TEXT,
        ip_address TEXT,
        mac_address TEXT,
        topic TEXT,
        last_seen REAL,
        current_scenario TEXT DEFAULT 'TH0_NORMAL',
        status TEXT DEFAULT 'offline',
        enabled INTEGER DEFAULT 1
    )
    """)

    # 2. Bảng lưu trữ đặc trưng theo cửa sổ thời gian (Feature Windows)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS windows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts_start REAL NOT NULL,
        ts_end REAL NOT NULL,
        device_key TEXT NOT NULL,
        feature_json TEXT NOT NULL,
        source TEXT DEFAULT 'live_capture',
        capture_id TEXT,
        created_at REAL NOT NULL
    )
    """)

    # 3. Bảng cảnh báo bất thường (Alerts)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL,
        device_key TEXT NOT NULL,
        score REAL,
        predicted_label TEXT NOT NULL,
        severity TEXT NOT NULL,
        model_version TEXT NOT NULL,
        alert_type TEXT NOT NULL, -- 'ml' hoặc 'rule'
        reason_json TEXT,
        status TEXT DEFAULT 'new'
    )
    """)

    # 4. Bảng lưu trữ kết quả thực nghiệm offline (Experiments)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dataset_name TEXT NOT NULL,
        model_name TEXT NOT NULL,
        config_json TEXT,
        split_id TEXT,
        metrics_json TEXT NOT NULL,
        created_at REAL NOT NULL
    )
    """)

    # 5. Bảng nhật ký sự kiện hệ thống (System Events)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        component TEXT NOT NULL,
        level TEXT NOT NULL,
        message TEXT NOT NULL,
        correlation_id TEXT
    )
    """)

    # 6. Bảng gói tin bắt trực tiếp từ Tshark (Wireshark CLI)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS packet_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        src_ip TEXT,
        dst_ip TEXT,
        frame_len INTEGER,
        tcp_flags TEXT,
        mqtt_type TEXT,
        device_key TEXT,
        info TEXT
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS observation_packets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts REAL NOT NULL,
        device_key TEXT NOT NULL,
        src_ip TEXT,
        dst_ip TEXT,
        frame_len INTEGER NOT NULL,
        tcp_flags TEXT,
        mqtt_type TEXT,
        info TEXT
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS observation_packets_ts ON observation_packets (ts)")
    cursor.execute("CREATE INDEX IF NOT EXISTS alerts_recent ON alerts (created_at DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS windows_device_created ON windows (device_key, created_at)")

    # Khởi tạo mặc định 6 thiết bị ESP32-S3 nếu chưa có
    default_devices = [
        ("esp32_01", "ESP32-S3 Node 1", "Hardware (ESP32-S3)", "NODE-01", "wievac/esp32_01/telemetry", "TH0_NORMAL"),
        ("esp32_02", "ESP32-S3 Node 2", "Hardware (ESP32-S3)", "NODE-02", "wievac/esp32_02/telemetry", "TH1_HIGH_RATE"),
        ("esp32_03", "ESP32-S3 Node 3", "Hardware (ESP32-S3)", "NODE-03", "wievac/esp32_03/telemetry", "TH2_LARGE_PAYLOAD"),
        ("esp32_04", "ESP32-S3 Node 4", "Hardware (ESP32-S3)", "NODE-04", "wievac/esp32_04/telemetry", "TH3_RECONNECT"),
        ("esp32_05", "ESP32-S3 Node 5", "Hardware (ESP32-S3)", "NODE-05", "wievac/esp32_05/telemetry", "TH5_BURST"),
        ("esp32_06", "ESP32-S3 Node 6", "Hardware (ESP32-S3)", "NODE-06", "wievac/esp32_06/telemetry", "TH4_SILENCE"),
    ]

    for d_id, name, d_type, pseudo, topic, sc in default_devices:
        cursor.execute("""
        INSERT OR IGNORE INTO devices (id, display_name, device_type, pseudonym, topic, current_scenario, status, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, 'offline', 0)
        """, (d_id, name, d_type, pseudo, topic, sc))

    conn.commit()
    conn.close()
    print("Khởi tạo SQLite Database thành công tại:", DB_PATH)


def prune_old_records(max_windows=10000, max_packets=5000):
    """Giữ bản ghi mới theo ID và giới hạn lịch sử cảnh báo ở 5.000 bản ghi."""
    try:
        with closing(get_db_connection()) as conn, conn:
            retention = (("windows", max_windows, "<"), ("packet_logs", max_packets, "<"), ("alerts", 5000, "<="))
            for table, keep, comparison in retention:
                conn.execute(
                    f"""DELETE FROM {table} WHERE id {comparison} (
                        SELECT id FROM {table} ORDER BY id DESC LIMIT 1 OFFSET ?
                    )""",
                    (max(0, keep),),
                )
    except sqlite3.Error as e:
        print("[DB] Lỗi khi dọn dẹp bản ghi cũ:", e)


if __name__ == "__main__":
    init_db()
    prune_old_records()

