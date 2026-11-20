import argparse
import json
import os
import sys
import time
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from pipeline.window_features import (
    FEATURE_COLUMNS_14,
    FEATURE_DESCRIPTIONS_14,
    compute_window_features_14,
    read_pcapng_packets,
)

DEFAULT_SESSIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "sessions"))
DEFAULT_CSV_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed", "local_feature_windows.csv"))
DEFAULT_REPORT_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "models", "artifacts", "local_extract_report.json"))
DEFAULT_LOG_OUT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs", "extract_features.log"))

FALLBACK_META = [
    ("TH0", "TH0_Normal", "normal", 0, "Gửi định kỳ 2s"),
    ("TH1", "TH1_HighRate", "high_rate", 1, "Bắn nhanh ~15 msg/s"),
    ("TH2", "TH2_LargePayload", "large_payload", 1, "Payload lớn ~1.5 KB"),
    ("TH3", "TH3_Reconnect", "reconnect", 1, "Connect/Drop 3s"),
    ("TH4", "TH4_Silence", "silence", 1, "Ngắt kết nối / Im lặng"),
    ("TH5", "TH5_BurstTraffic", "burst", 1, "Xung nhịp ngắt quãng"),
    ("TH6", "TH6_AuthFail", "auth_fail", 1, "Sai User/Pass MQTT"),
]


def _resolve_device_ips(packets):
    ip_map = {}
    for p in packets:
        esp_ip = p["dst_ip"] if p["sport"] == 1883 else p["src_ip"]
        cid = p.get("client_id", "")
        topic = p.get("topic", "")
        if cid.startswith("esp32_"):
            ip_map[cid] = esp_ip
        elif topic:
            for part in topic.split("/"):
                if part.startswith("esp32_"):
                    ip_map[part] = esp_ip
                    break
    return ip_map


def _discover_batches(sessions_dir):
    """Phát hiện các thư mục batch_* (hoặc thư mục gốc nếu chứa trực tiếp .pcapng)."""
    if not os.path.isdir(sessions_dir):
        return []

    batches = []
    for entry in sorted(os.listdir(sessions_dir)):
        full = os.path.join(sessions_dir, entry)
        if not os.path.isdir(full):
            continue
        has_manifest = os.path.exists(os.path.join(full, "session_manifest.json"))
        has_pcap = any(f.endswith(".pcapng") or f.endswith(".pcap") for f in os.listdir(full))
        if has_manifest or has_pcap:
            batches.append((entry, full))

    has_root_manifest = os.path.exists(os.path.join(sessions_dir, "session_manifest.json"))
    has_root_pcap = any(f.endswith(".pcapng") or f.endswith(".pcap") for f in os.listdir(sessions_dir))
    if has_root_manifest or has_root_pcap:
        batches.append(("batch_01" if not batches else "root", sessions_dir))

    return batches


def extract_sessions(sessions_dir=DEFAULT_SESSIONS_DIR, csv_out=DEFAULT_CSV_OUT, report_out=DEFAULT_REPORT_OUT, window_size=5.0):
    t0 = time.time()
    logs = []

    def log(msg=""):
        print(msg)
        logs.append(msg)

    log("======================================================================")
    log("BƯỚC 1: QUÉT VÀ NHẬN DIỆN CÁC PHIÊN THU DỮ LIỆU (SESSIONS)")
    log("======================================================================")

    batches = _discover_batches(sessions_dir)
    sessions = []
    for batch_name, bdir in batches:
        manifest_path = os.path.join(bdir, "session_manifest.json")
        manifest = None
        if os.path.exists(manifest_path):
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)

        batch_ip_map = dict(manifest.get("node_ips", {})) if manifest else {}
        if manifest and manifest.get("sessions"):
            for s in manifest["sessions"]:
                fpath = os.path.join(bdir, s["filename"])
                if os.path.exists(fpath):
                    sessions.append(dict(s, filepath=fpath, batch=batch_name, batch_ip_map=batch_ip_map))
        else:
            all_files = sorted(os.listdir(bdir))
            for code, prefix, sc_label, bin_label, desc in FALLBACK_META:
                match = next((f for f in all_files if f.startswith(prefix) and (f.endswith(".pcapng") or f.endswith(".pcap"))), None)
                if match:
                    fpath = os.path.join(bdir, match)
                    sessions.append({
                        "scenario_code": code,
                        "filename": match,
                        "scenario_label": sc_label,
                        "binary_label": bin_label,
                        "description": desc,
                        "assigned_nodes": [],
                        "filepath": fpath,
                        "batch": batch_name,
                        "batch_ip_map": batch_ip_map,
                    })

    if not sessions:
        raise FileNotFoundError(f"Không tìm thấy file .pcapng nào trong {sessions_dir}")

    multi_batch = len(batches) > 1
    total_raw_packets = 0
    total_duration_sec = 0.0
    parsed_sessions = []

    for idx, s in enumerate(sessions, 1):
        pkts = read_pcapng_packets(s["filepath"], target_port=1883)
        s["batch_ip_map"].update(_resolve_device_ips(pkts))
        fsize_kb = os.path.getsize(s["filepath"]) / 1024.0

        start_ts = s.get("start_ts") or (min(p["ts"] for p in pkts) if pkts else 0.0)
        end_ts = s.get("end_ts") or (max(p["ts"] for p in pkts) if pkts else start_ts)
        dur_sec = s.get("duration_sec") or max(0.0, end_ts - start_ts)

        total_raw_packets += len(pkts)
        total_duration_sec += dur_sec

        s_enriched = dict(s)
        s_enriched["packets"] = pkts
        s_enriched["start_ts"] = start_ts
        s_enriched["end_ts"] = end_ts
        s_enriched["duration_sec"] = dur_sec
        s_enriched["raw_packet_count"] = len(pkts)
        s_enriched["size_kb"] = round(fsize_kb, 2)
        s_enriched["display_name"] = f"{s['batch']}/{s['filename']}" if multi_batch else s["filename"]
        parsed_sessions.append(s_enriched)

    log(f"[DISCOVER] Tìm thấy {len(parsed_sessions)} phiên thu trên {len(batches)} đợt (batch):")
    session_summaries = []
    for idx, s in enumerate(parsed_sessions):
        branch = "└──" if idx == len(parsed_sessions) - 1 else "├──"
        nodes_str = ",".join(s.get("assigned_nodes") or ["auto"])
        size_str = f"{s['size_kb']/1024:.2f} MB" if s["size_kb"] >= 1024 else f"{s['size_kb']:.1f} KB"
        log(
            f"  {branch} [Session {idx+1:02d}] {s['display_name']:<30} | {nodes_str:<10} | "
            f"{s['description']:<26} | {s['duration_sec']/60:.1f} phút | {s['raw_packet_count']:,} gói | {size_str}"
        )
        session_summaries.append({
            "session": idx + 1,
            "batch": s["batch"],
            "filename": s["display_name"],
            "scenario_code": s["scenario_code"],
            "scenario_label": s["scenario_label"],
            "binary_label": s["binary_label"],
            "assigned_nodes": s.get("assigned_nodes") or [],
            "duration_min": round(s["duration_sec"] / 60.0, 2),
            "raw_packets": s["raw_packet_count"],
            "size_kb": s["size_kb"],
        })

    log(f"-> [TỔNG CỘNG] {len(parsed_sessions)} phiên thu ({len(batches)} batch) | Thời lượng: {total_duration_sec/60:.1f} phút | Tổng gói tin thô: {total_raw_packets:,} gói.")

    log("======================================================================")
    log(f"BƯỚC 2: CẮT LÁT THEO CỬA SỔ THỜI GIAN (TIME-WINDOWING: T = {window_size:.1f} GIÂY)")
    log("======================================================================")
    log(f"[CONFIG] Cửa sổ thời gian (Window Size): {window_size:.1f} giây | Bước nhảy (Stride): {window_size:.1f} giây (Non-overlapping)")
    log("[PROCESS] Đang trích xuất đặc trưng cho từng phiên...")

    all_rows = []
    for idx, s in enumerate(parsed_sessions):
        pkts = s["packets"]
        sc_code = s["scenario_code"]
        sc_label = s["scenario_label"]
        bin_label = s["binary_label"]
        assigned = set(s.get("assigned_nodes") or [])
        ip_to_dev = {ip: dev for dev, ip in s["batch_ip_map"].items()}

        # Nhóm gói theo device_key dựa vào IP thật (tránh node hết pin bật lại làm nhiễu phiên tấn công)
        per_dev_packets = {}
        for p in pkts:
            dev = ip_to_dev.get(p["src_ip"]) or ip_to_dev.get(p["dst_ip"])
            if not dev:
                continue
            if assigned and dev not in assigned:
                continue
            per_dev_packets.setdefault(dev, []).append(p)

        # Với TH4_Silence vẫn đảm bảo node được phân công xuất hiện kể cả khi 0 gói
        if sc_code == "TH4":
            for dev in assigned:
                per_dev_packets.setdefault(dev, [])

        start_ts = s["start_ts"]
        end_ts = s["end_ts"]
        win_count = 0
        empty_count = 0
        dropped_empty = 0

        if end_ts > start_ts and per_dev_packets:
            cur = start_ts
            while cur + window_size <= end_ts + 0.01:
                w_end = cur + window_size
                for dev, dev_pkts in sorted(per_dev_packets.items()):
                    w_pkts = [p for p in dev_pkts if cur <= p["ts"] < w_end]
                    if len(w_pkts) == 0 and sc_code != "TH4":
                        # Chống nhiễu mất pin: phiên có phát tin mà 0 gói thì bỏ qua, không gắn nhầm nhãn
                        dropped_empty += 1
                        continue
                    feats = compute_window_features_14(w_pkts, window_size=window_size)
                    if feats["is_empty_window"] == 1:
                        empty_count += 1
                    row = {
                        "batch": s["batch"],
                        "device_key": dev,
                        "window_start": round(cur, 3),
                        "window_end": round(w_end, 3),
                    }
                    row.update(feats)
                    row["binary_label"] = bin_label
                    row["scenario_label"] = sc_label
                    all_rows.append(row)
                    win_count += 1
                cur = w_end

        session_summaries[idx]["windows_extracted"] = win_count
        session_summaries[idx]["empty_windows_kept"] = empty_count
        session_summaries[idx]["empty_windows_skipped"] = dropped_empty

        extra = f" (Trong đó: {empty_count} cửa sổ rỗng = 0 gói)" if sc_code == "TH4" else (f" (Đã loại {dropped_empty} cửa sổ rỗng do node tắt/hết pin)" if dropped_empty > 0 else "")
        batch_tag = f"[{s['batch']}] " if multi_batch else ""
        log(f"  -> {batch_tag}Phiên {sc_code} ({sc_label:<13}): {win_count:>4} cửa sổ thời gian{extra}")

    log(f"-> [TỔNG CỘNG ĐÃ TẠO]: {len(all_rows):,} cửa sổ thời gian (Windows).")

    log("======================================================================")
    log("BƯỚC 3: TÍNH TOÁN BỘ ĐẶC TRƯNG CỬA SỔ (FEATURE EXTRACTION)")
    log("======================================================================")
    log(f"[SCHEMA] Đã tính {len(FEATURE_COLUMNS_14)} đặc trưng lưu lượng mạng cho mỗi cửa sổ {window_size:.0f}s:")
    for i, col in enumerate(FEATURE_COLUMNS_14, 1):
        log(f"  {i:>2}. {col:<18} : {FEATURE_DESCRIPTIONS_14[col]}")

    log("======================================================================")
    log("BƯỚC 4: XUẤT TẬP DỮ LIỆU ĐẶC TRƯNG CHO MÁY HỌC (FEATURE DATASET)")
    log("======================================================================")
    df = pd.DataFrame(all_rows)
    os.makedirs(os.path.dirname(csv_out), exist_ok=True)
    df.to_csv(csv_out, index=False, encoding="utf-8")

    n_norm = int((df["binary_label"] == 0).sum()) if not df.empty else 0
    n_anom = int((df["binary_label"] == 1).sum()) if not df.empty else 0
    scenarios_present = sorted(df["scenario_label"].unique().tolist()) if not df.empty else []

    log("[METADATA] Đã gán nhãn ground_truth:")
    log(f"  - Nhãn nhị phân (binary_label): 0 = Normal ({n_norm} mẫu), 1 = Anomaly ({n_anom} mẫu)")
    log(f"  - Nhãn chi tiết (scenario_label): {', '.join(scenarios_present)}")
    log("[OUTPUT] Đã xuất file đặc trưng hoàn chỉnh vào:")
    log(f"  -> {csv_out} ({len(df):,} dòng x {len(df.columns)} cột)")
    elapsed = time.time() - t0
    log(f"[SUCCESS] Pipeline trích xuất đặc trưng hoàn tất trong {elapsed:.2f} giây!")

    report = {
        "created_at": time.time(),
        "window_size_sec": window_size,
        "total_batches": len(batches),
        "total_sessions": len(parsed_sessions),
        "total_duration_min": round(total_duration_sec / 60.0, 2),
        "total_raw_packets": total_raw_packets,
        "total_windows": len(df),
        "normal_windows": n_norm,
        "anomaly_windows": n_anom,
        "feature_columns": FEATURE_COLUMNS_14,
        "csv_path": csv_out,
        "sessions": session_summaries,
        "extract_log": "\n".join(logs),
    }
    os.makedirs(os.path.dirname(report_out), exist_ok=True)
    with open(report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    os.makedirs(os.path.dirname(DEFAULT_LOG_OUT), exist_ok=True)
    with open(DEFAULT_LOG_OUT, "w", encoding="utf-8") as f:
        f.write(report["extract_log"] + "\n")

    return df, report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trích xuất 14 đặc trưng cửa sổ 5s từ các phiên .pcapng")
    parser.add_argument("--sessions-dir", default=DEFAULT_SESSIONS_DIR)
    parser.add_argument("--csv-out", default=DEFAULT_CSV_OUT)
    parser.add_argument("--report-out", default=DEFAULT_REPORT_OUT)
    parser.add_argument("--window", type=float, default=5.0)
    args = parser.parse_args()
    extract_sessions(args.sessions_dir, args.csv_out, args.report_out, args.window)

