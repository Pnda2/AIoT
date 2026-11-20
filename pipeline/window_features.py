import socket
import struct
import numpy as np

FEATURE_COLUMNS_14 = [
    "packet_count",
    "byte_count",
    "packet_rate",
    "byte_rate",
    "len_mean",
    "len_std",
    "len_max",
    "iat_mean",
    "iat_std",
    "iat_max",
    "tcp_syn_count",
    "tcp_fin_count",
    "tcp_rst_count",
    "is_empty_window",
]

FEATURE_DESCRIPTIONS_14 = {
    "packet_count": "Tổng số gói tin trong 5s (gói)",
    "byte_count": "Tổng lưu lượng trong 5s (bytes)",
    "packet_rate": "Tần suất gói (packet_count / 5.0)",
    "byte_rate": "Tốc độ băng thông (byte_count / 5.0)",
    "len_mean": "Kích thước gói tin trung bình (bytes)",
    "len_std": "Độ lệch chuẩn kích thước gói (bytes)",
    "len_max": "Kích thước gói lớn nhất (bytes)",
    "iat_mean": "Khoảng cách thời gian trung bình giữa 2 gói (ms)",
    "iat_std": "Độ lệch chuẩn IAT (ms)",
    "iat_max": "Khoảng cách thời gian lớn nhất giữa 2 gói (ms)",
    "tcp_syn_count": "Số lượng cờ SYN (phát hiện kết nối/reconnect)",
    "tcp_fin_count": "Số lượng cờ FIN (ngắt kết nối)",
    "tcp_rst_count": "Số lượng cờ RST (từ chối/lỗi bắt tay)",
    "is_empty_window": "Cờ báo cửa sổ rỗng (0 gói - dành cho Watchdog TH4)",
}


def compute_window_features_14(packets, window_size=5.0):
    """Tính đúng 14 đặc trưng lưu lượng chuẩn hóa cho 1 cửa sổ thời gian (dùng chung Offline & Live)."""
    if not packets:
        return {
            "packet_count": 0,
            "byte_count": 0,
            "packet_rate": 0.0,
            "byte_rate": 0.0,
            "len_mean": 0.0,
            "len_std": 0.0,
            "len_max": 0,
            "iat_mean": 0.0,
            "iat_std": 0.0,
            "iat_max": 0.0,
            "tcp_syn_count": 0,
            "tcp_fin_count": 0,
            "tcp_rst_count": 0,
            "is_empty_window": 1,
        }

    packet_count = len(packets)
    lengths = [int(p["len"]) for p in packets]
    byte_count = int(sum(lengths))
    len_mean = float(np.mean(lengths))
    len_std = float(np.std(lengths))
    len_max = int(max(lengths))

    ts_sorted = sorted(float(p["ts"]) for p in packets)
    if len(ts_sorted) >= 2:
        iats_ms = np.diff(ts_sorted) * 1000.0
        iat_mean = float(np.mean(iats_ms))
        iat_std = float(np.std(iats_ms))
        iat_max = float(np.max(iats_ms))
    else:
        # 1 gói trong 5s -> không có khoảng trễ nhỏ giữa các gói (đặt bằng 1 chu kỳ cửa sổ để tránh nhầm với flood IAT=0)
        iat_mean = float(window_size * 1000.0)
        iat_std = 0.0
        iat_max = float(window_size * 1000.0)

    return {
        "packet_count": packet_count,
        "byte_count": byte_count,
        "packet_rate": round(packet_count / window_size, 4),
        "byte_rate": round(byte_count / window_size, 2),
        "len_mean": round(len_mean, 2),
        "len_std": round(len_std, 2),
        "len_max": len_max,
        "iat_mean": round(iat_mean, 2),
        "iat_std": round(iat_std, 2),
        "iat_max": round(iat_max, 2),
        "tcp_syn_count": int(sum(1 for p in packets if p.get("syn"))),
        "tcp_fin_count": int(sum(1 for p in packets if p.get("fin"))),
        "tcp_rst_count": int(sum(1 for p in packets if p.get("rst"))),
        "is_empty_window": 0,
    }


def _decode_mqtt_meta(payload):
    """Trích xuất nhẹ loại gói MQTT, topic (PUBLISH) hoặc client_id (CONNECT) từ TCP payload."""
    if len(payload) < 2:
        return None, "", ""
    msg_type = (payload[0] >> 4) & 0x0F

    # Giải mã Remaining Length (MQTT varint 1..4 bytes)
    idx = 1
    rem_len = 0
    mult = 1
    while idx < len(payload) and idx <= 4:
        b = payload[idx]
        rem_len += (b & 0x7F) * mult
        idx += 1
        if (b & 0x80) == 0:
            break
        mult *= 128

    body = payload[idx:]
    if msg_type == 3 and len(body) >= 2:  # PUBLISH -> topic UTF-8
        tlen = struct.unpack(">H", body[:2])[0]
        if 2 + tlen <= len(body):
            topic = body[2 : 2 + tlen].decode("utf-8", errors="ignore")
            return msg_type, topic, ""
    elif msg_type == 1 and len(body) >= 2:  # CONNECT -> client_id
        plen = struct.unpack(">H", body[:2])[0]
        pos = 2 + plen + 4  # proto_name + proto_level(1) + flags(1) + keepalive(2)
        if pos + 2 <= len(body):
            clen = struct.unpack(">H", body[pos : pos + 2])[0]
            if pos + 2 + clen <= len(body):
                cid = body[pos + 2 : pos + 2 + clen].decode("utf-8", errors="ignore")
                return msg_type, "", cid
    return msg_type, "", ""


def _parse_tcp_ipv4_frame(pkt, link_type=1):
    """Giải mã frame Ethernet (hoặc Linux SLL) -> thông tin gói TCP/MQTT."""
    if link_type == 1:  # Ethernet
        if len(pkt) < 14:
            return None
        eth_type = struct.unpack(">H", pkt[12:14])[0]
        ip_off = 14
        if eth_type == 0x8100 and len(pkt) >= 18:
            eth_type = struct.unpack(">H", pkt[16:18])[0]
            ip_off = 18
        if eth_type != 0x0800:
            return None
    elif link_type == 113:  # Linux cooked SLL
        if len(pkt) < 16:
            return None
        eth_type = struct.unpack(">H", pkt[14:16])[0]
        ip_off = 16
        if eth_type != 0x0800:
            return None
    else:
        return None

    if len(pkt) < ip_off + 20:
        return None
    ver_ihl = pkt[ip_off]
    if (ver_ihl >> 4) != 4:
        return None
    ihl = (ver_ihl & 0x0F) * 4
    ip_total = struct.unpack(">H", pkt[ip_off + 2 : ip_off + 4])[0]
    proto = pkt[ip_off + 9]
    if proto != 6 or len(pkt) < ip_off + ihl + 14:
        return None

    src_ip = socket.inet_ntoa(pkt[ip_off + 12 : ip_off + 16])
    dst_ip = socket.inet_ntoa(pkt[ip_off + 16 : ip_off + 20])
    tcp_off = ip_off + ihl
    sport, dport = struct.unpack(">HH", pkt[tcp_off : tcp_off + 4])
    tcp_hlen = ((pkt[tcp_off + 12] >> 4) & 0x0F) * 4
    flags = pkt[tcp_off + 13]

    fin = bool(flags & 0x01)
    syn = bool(flags & 0x02)
    rst = bool(flags & 0x04)
    ack = bool(flags & 0x10)

    payload_start = tcp_off + tcp_hlen
    payload_end = min(len(pkt), ip_off + ip_total) if ip_total >= ihl + tcp_hlen else len(pkt)
    tcp_payload = pkt[payload_start:payload_end] if payload_end > payload_start else b""
    mqtt_type, topic, client_id = _decode_mqtt_meta(tcp_payload)

    return {
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "sport": sport,
        "dport": dport,
        "syn": syn and not ack,  # Chỉ tính SYN mở kết nối mới (tránh đếm trùng SYN-ACK)
        "fin": fin,
        "rst": rst,
        "mqtt_type": mqtt_type,
        "topic": topic,
        "client_id": client_id,
    }


def read_pcapng_packets(filepath, target_port=1883):
    """Đọc file .pcapng / .pcap thuần Python (chạy được trên cả Windows và Pi 5 không cần Wireshark)."""
    with open(filepath, "rb") as f:
        data = f.read()

    if len(data) < 24:
        return []

    magic4 = struct.unpack("<I", data[:4])[0]
    # Hỗ trợ thêm file .pcap cổ điển nếu có
    if magic4 in (0xA1B2C3D4, 0xD4C3B2A1, 0xA1B23C4D, 0x4D3CB2A1):
        return _read_legacy_pcap(data, magic4, target_port)

    packets = []
    pos = 0
    endian = "<"
    interfaces = []

    while pos + 12 <= len(data):
        btype = struct.unpack(endian + "I", data[pos : pos + 4])[0]
        if btype == 0x0A0D0D0A:
            # Section Header Block kiểm tra endian tại byte 8..12
            if struct.unpack("<I", data[pos + 8 : pos + 12])[0] == 0x1A2B3C4D:
                endian = "<"
            else:
                endian = ">"
            blen = struct.unpack(endian + "I", data[pos + 4 : pos + 8])[0]
            interfaces = []
            if blen < 28 or pos + blen > len(data):
                break
            pos += blen
            continue

        blen = struct.unpack(endian + "I", data[pos + 4 : pos + 8])[0]
        if blen < 12 or pos + blen > len(data):
            break

        if btype == 0x00000001 and blen >= 20:  # IDB
            link_type = struct.unpack(endian + "H", data[pos + 8 : pos + 10])[0]
            ts_unit = 1e-6  # mặc định microsecond
            opt_pos = pos + 16
            opt_end = pos + blen - 4
            while opt_pos + 4 <= opt_end:
                ocode, olen = struct.unpack(endian + "HH", data[opt_pos : opt_pos + 4])
                opt_pos += 4
                if ocode == 0:
                    break
                if ocode == 9 and olen >= 1 and opt_pos < opt_end:  # if_tsresol
                    val = data[opt_pos]
                    if (val & 0x80) == 0:
                        ts_unit = 10.0 ** (-val)
                    else:
                        ts_unit = 2.0 ** (-(val & 0x7F))
                padded = (olen + 3) & ~3
                opt_pos += padded
            interfaces.append((link_type, ts_unit))

        elif btype == 0x00000006 and blen >= 32:  # EPB
            iface_id, ts_hi, ts_lo, cap_len, orig_len = struct.unpack(
                endian + "5I", data[pos + 8 : pos + 28]
            )
            link_type, ts_unit = interfaces[iface_id] if iface_id < len(interfaces) else (1, 1e-6)
            ts = ((ts_hi << 32) | ts_lo) * ts_unit
            raw_pkt = data[pos + 28 : pos + 28 + cap_len]
            parsed = _parse_tcp_ipv4_frame(raw_pkt, link_type=link_type)
            if parsed and (target_port is None or parsed["sport"] == target_port or parsed["dport"] == target_port):
                parsed["ts"] = ts
                parsed["len"] = orig_len
                packets.append(parsed)

        pos += blen

    return packets


def _read_legacy_pcap(data, magic4, target_port=1883):
    endian = "<" if magic4 in (0xA1B2C3D4, 0xA1B23C4D) else ">"
    ts_div = 1e-9 if magic4 in (0xA1B23C4D, 0x4D3CB2A1) else 1e-6
    link_type = struct.unpack(endian + "I", data[20:24])[0]
    packets = []
    pos = 24
    while pos + 16 <= len(data):
        ts_sec, ts_sub, cap_len, orig_len = struct.unpack(endian + "4I", data[pos : pos + 16])
        pos += 16
        if pos + cap_len > len(data):
            break
        raw_pkt = data[pos : pos + cap_len]
        pos += cap_len
        parsed = _parse_tcp_ipv4_frame(raw_pkt, link_type=link_type)
        if parsed and (target_port is None or parsed["sport"] == target_port or parsed["dport"] == target_port):
            parsed["ts"] = ts_sec + ts_sub * ts_div
            parsed["len"] = orig_len
            packets.append(parsed)
    return packets

