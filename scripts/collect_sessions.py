#!/usr/bin/env python3
"""
SCRIPT TỰ ĐỘNG THU THẬP 7 PHIÊN DỮ LIỆU THẬT TRÊN RASPBERRY PI 5
Ghi ra 7 file .pcapng riêng biệt trong data/sessions/ kèm session_manifest.json.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
from pipeline.window_features import read_pcapng_packets

SESSIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "sessions"))
MOSQ_CONF = "/etc/mosquitto/conf.d/iot_lab.conf"
MOSQ_PASSWD = "/etc/mosquitto/passwd_lab"

SESSIONS_PLAN = [
    ("TH0", "TH0_Normal.pcapng", "normal", 0, "Gửi định kỳ 2s (tất cả node online)"),
    ("TH1", "TH1_HighRate.pcapng", "high_rate", 1, "Bắn nhanh ~15 msg/s"),
    ("TH2", "TH2_LargePayload.pcapng", "large_payload", 1, "Payload lớn ~1.5 KB"),
    ("TH3", "TH3_Reconnect.pcapng", "reconnect", 1, "Connect/Drop 3s liên tục"),
    ("TH4", "TH4_Silence.pcapng", "silence", 1, "Im lặng / Mất kết nối"),
    ("TH5", "TH5_BurstTraffic.pcapng", "burst", 1, "Xả dồn 20 gói theo đợt"),
    ("TH6", "TH6_AuthFail.pcapng", "auth_fail", 1, "Thử xác thực sai User/Pass MQTT"),
]


def discover_online_nodes(timeout_sec=6.0):
    found = {}

    def on_msg(client, userdata, msg):
        parts = msg.topic.split("/")
        if len(parts) >= 2 and parts[1].startswith("esp32_"):
            found[parts[1]] = time.time()

    c = mqtt.Client(client_id="session_collector_probe")
    c.on_message = on_msg
    c.connect("127.0.0.1", 1883, 60)
    c.subscribe("wievac/+/telemetry")
    c.loop_start()
    time.sleep(timeout_sec)
    c.loop_stop()
    c.disconnect()
    return sorted(found.keys())


def send_scenario(node_ids, scenario, retain=False):
    for nid in node_ids:
        publish.single(f"wievac/control/{nid}", scenario, hostname="127.0.0.1", port=1883, retain=retain)


def record_pcap(filepath, duration_sec, interface="wlan0"):
    if os.path.exists(filepath):
        os.remove(filepath)
    cmd = [
        "dumpcap", "-q", "-i", interface,
        "-f", "port 1883",
        "-a", f"duration:{int(duration_sec)}",
        "-w", filepath,
    ]
    subprocess.run(cmd, check=True)


def extract_ips_from_pcap(filepath):
    """Dò IP <-> device_key từ gói MQTT PUBLISH/CONNECT vừa quay."""
    mapping = {}
    if not os.path.exists(filepath):
        return mapping
    for p in read_pcapng_packets(filepath, target_port=1883):
        esp_ip = p["dst_ip"] if p["sport"] == 1883 else p["src_ip"]
        cid = p.get("client_id", "")
        topic = p.get("topic", "")
        if cid.startswith("esp32_"):
            mapping[cid] = esp_ip
        elif topic:
            for part in topic.split("/"):
                if part.startswith("esp32_"):
                    mapping[part] = esp_ip
                    break
    return mapping


def set_mosquitto_auth(enable_auth=False):
    if enable_auth:
        subprocess.run(["sudo", "mosquitto_passwd", "-b", "-c", MOSQ_PASSWD, "lab_ok", "lab_secret_123"], check=True)
        conf = f"listener 1883 0.0.0.0\nallow_anonymous false\npassword_file {MOSQ_PASSWD}\n"
    else:
        conf = "listener 1883 0.0.0.0\nallow_anonymous true\n"
    subprocess.run(["sudo", "tee", MOSQ_CONF], input=conf, text=True, stdout=subprocess.DEVNULL, check=True)
    subprocess.run(["sudo", "systemctl", "restart", "mosquitto"], check=True)
    time.sleep(2)


def resolve_batch_dir(base_dir, batch_arg):
    os.makedirs(base_dir, exist_ok=True)
    if batch_arg and batch_arg.lower() != "auto":
        if batch_arg.lower() == "root":
            return "", base_dir
        bdir = os.path.join(base_dir, batch_arg)
        os.makedirs(bdir, exist_ok=True)
        return batch_arg, bdir

    existing_nums = []
    for entry in os.listdir(base_dir):
        full = os.path.join(base_dir, entry)
        if os.path.isdir(full) and entry.startswith("batch_"):
            suffix = entry[len("batch_"):]
            if suffix.isdigit():
                existing_nums.append(int(suffix))
    has_root_pcap = any(f.endswith(".pcapng") or f.endswith(".pcap") for f in os.listdir(base_dir))
    next_idx = max(existing_nums, default=(1 if has_root_pcap else 0)) + 1
    bname = f"batch_{next_idx:02d}"
    bdir = os.path.join(base_dir, bname)
    os.makedirs(bdir, exist_ok=True)
    return bname, bdir


def main():
    parser = argparse.ArgumentParser(description="Thu thập tự động 7 phiên .pcapng từ ESP32 trên Raspberry Pi 5")
    parser.add_argument("--th0-mins", type=float, default=5.0, help="Thời lượng thu TH0 Normal (phút)")
    parser.add_argument("--attack-mins", type=float, default=2.0, help="Thời lượng thu mỗi kịch bản TH1..TH6 (phút)")
    parser.add_argument("--attack-node", type=str, default="", help="Node dùng cho TH1..TH6 (VD: esp32_06). Mặc định tự chọn node đang online.")
    parser.add_argument("--interface", type=str, default="wlan0", help="Card mạng thu gói")
    parser.add_argument("--batch", type=str, default="auto", help="Tên thư mục batch con (VD: batch_02, hoặc auto để tự đánh số tăng dần)")
    args = parser.parse_args()

    batch_name, batch_dir = resolve_batch_dir(SESSIONS_DIR, args.batch)
    print("======================================================================")
    print(f"BẮT ĐẦU PHIÊN THU DỮ LIỆU THẬT TỰ ĐỘNG TRÊN RASPBERRY PI 5 ({batch_name or 'root'})")
    print("======================================================================")

    print("[1/4] Tạm dừng iot_pipeline để dumpcap thu riêng từng phiên sạch sẽ...")
    subprocess.run(["sudo", "systemctl", "stop", "iot_pipeline"], check=False)

    online_nodes = discover_online_nodes(6.0)
    if not online_nodes:
        print("[LỖI] Không phát hiện node ESP32 nào đang online qua MQTT. Hãy kiểm tra nguồn các node!")
        subprocess.run(["sudo", "systemctl", "start", "iot_pipeline"], check=False)
        sys.exit(1)

    target_node = args.attack_node if args.attack_node in online_nodes else ("esp32_06" if "esp32_06" in online_nodes else online_nodes[-1])
    print(f"[INFO] Phát hiện {len(online_nodes)} node online: {online_nodes}")
    print(f"[INFO] Node thực hiện các phiên tấn công TH1..TH6: {target_node}")

    manifest = {
        "batch": batch_name or "batch_01",
        "created_at": time.time(),
        "interface": args.interface,
        "all_online_nodes": online_nodes,
        "target_attack_node": target_node,
        "node_ips": {},
        "sessions": [],
    }

    try:
        for sc_code, fname, sc_label, bin_label, desc in SESSIONS_PLAN:
            dur_sec = max(30, int((args.th0_mins if sc_code == "TH0" else args.attack_mins) * 60))
            out_path = os.path.join(batch_dir, fname)
            assigned = online_nodes if sc_code == "TH0" else [target_node]

            print(f"\n--- Đang thu {sc_code} ({fname}) | {dur_sec}s | Nodes: {assigned} | {desc} ---")

            if sc_code == "TH6":
                send_scenario([target_node], "TH6")
                time.sleep(1.5)
                set_mosquitto_auth(enable_auth=True)
            else:
                send_scenario(assigned, sc_code)
                time.sleep(2.0)

            t_start = time.time()
            record_pcap(out_path, dur_sec, interface=args.interface)
            t_end = time.time()

            if sc_code == "TH6":
                set_mosquitto_auth(enable_auth=False)
                send_scenario([target_node], "TH0", retain=True)
                time.sleep(4.0)
                publish.single(f"wievac/control/{target_node}", "", hostname="127.0.0.1", port=1883, retain=True)
            elif sc_code != "TH0":
                send_scenario(assigned, "TH0")
                time.sleep(4.0)

            discovered_ips = extract_ips_from_pcap(out_path)
            manifest["node_ips"].update(discovered_ips)
            size_kb = round(os.path.getsize(out_path) / 1024.0, 2) if os.path.exists(out_path) else 0.0

            manifest["sessions"].append({
                "scenario_code": sc_code,
                "filename": fname,
                "scenario_label": sc_label,
                "binary_label": bin_label,
                "description": desc,
                "assigned_nodes": assigned,
                "start_ts": t_start,
                "end_ts": t_end,
                "duration_sec": dur_sec,
                "size_kb": size_kb,
            })
            print(f"    -> Xong {fname} ({size_kb} KB) | IP map: {manifest['node_ips']}")

        manifest_path = os.path.join(batch_dir, "session_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        print(f"\n[THÀNH CÔNG] Đã lưu toàn bộ 7 file .pcapng và manifest tại: {batch_dir}")
        print(f"[LƯU Ý] Nếu node {target_node} vẫn kẹt ở TH6 sau thử nghiệm, hãy nhấn nút RST trên mạch đó 1 lần để về TH0.")

    finally:
        # Đảm bảo khôi phục mosquitto và bật lại iot_pipeline trong mọi tình huống
        try:
            if os.path.exists(MOSQ_CONF):
                with open(MOSQ_CONF, "r", encoding="utf-8", errors="ignore") as f:
                    if "allow_anonymous false" in f.read():
                        set_mosquitto_auth(enable_auth=False)
        except Exception:
            pass
        subprocess.run(["sudo", "systemctl", "start", "iot_pipeline"], check=False)


if __name__ == "__main__":
    main()

