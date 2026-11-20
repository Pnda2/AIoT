import os
import sqlite3
import time

def prune_database(db_path, max_windows=10000, max_packets=5000):
    if not os.path.exists(db_path):
        print("Database not found at:", db_path)
        return

    size_before = os.path.getsize(db_path) / (1024 * 1024)
    conn = sqlite3.connect(db_path, timeout=30.0)
    cursor = conn.cursor()

    # 1. Đếm trước khi dọn
    cursor.execute("SELECT count(id) FROM windows")
    w_count_before = cursor.fetchone()[0]

    cursor.execute("SELECT count(id) FROM packet_logs")
    p_count_before = cursor.fetchone()[0]

    # 2. Xóa các cửa sổ cũ vượt quá max_windows
    if w_count_before > max_windows:
        cursor.execute(f"""
            DELETE FROM windows 
            WHERE id < (
                SELECT id FROM windows 
                ORDER BY id DESC 
                LIMIT 1 OFFSET {max_windows}
            )
        """)
        w_deleted = cursor.rowcount
    else:
        w_deleted = 0

    # 3. Xóa các gói packet_logs cũ vượt quá max_packets
    if p_count_before > max_packets:
        cursor.execute(f"""
            DELETE FROM packet_logs 
            WHERE id < (
                SELECT id FROM packet_logs 
                ORDER BY id DESC 
                LIMIT 1 OFFSET {max_packets}
            )
        """)
        p_deleted = cursor.rowcount
    else:
        p_deleted = 0

    # 3.5. Xóa các cảnh báo false alarm TRAFFIC_ANOMALY
    cursor.execute("DELETE FROM alerts WHERE predicted_label = 'TRAFFIC_ANOMALY'")
    alerts_deleted = cursor.rowcount

    conn.commit()

    # 4. Thu gọn dung lượng file (VACUUM)
    print(f"Đã xóa {alerts_deleted} cảnh báo giả TRAFFIC_ANOMALY.")
    print("Đang chạy VACUUM để giải phóng dung lượng đĩa...")
    cursor.execute("VACUUM")
    conn.close()

    size_after = os.path.getsize(db_path) / (1024 * 1024)

    # Đếm lại sau khi dọn
    conn2 = sqlite3.connect(db_path)
    c2 = conn2.cursor()
    c2.execute("SELECT count(id) FROM windows")
    w_count_after = c2.fetchone()[0]
    conn2.close()

    print(f"[DB PRUNE] Windows: {w_count_before} -> {w_count_after} (Đã xóa {w_deleted} dòng cũ)")
    print(f"[DB PRUNE] Packet Logs: Đã xóa {p_deleted} dòng cũ")
    print(f"[DB PRUNE] Dung lượng file: {size_before:.2f} MB -> {size_after:.2f} MB")

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "iot_system.db"))
    prune_database(path, max_windows=10000, max_packets=5000)
