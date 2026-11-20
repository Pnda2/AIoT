# AIoT - Hệ thống phát hiện xâm nhập và tấn công mạng IoT (Intrusion Detection System)

Dự án nghiên cứu và triển khai hệ thống giám sát an ninh mạng IoT sử dụng học máy (Machine Learning) kết hợp kiến trúc phòng thủ 2 lớp (Defense-in-Depth):
1. **Lớp biên (Edge - Raspberry Pi 5 / Gateway):** Sử dụng **Isolation Forest** (Học không giám sát) để phát hiện dị biệt thời gian thực, có khả năng phát hiện sớm các cuộc tấn công chưa từng biết (Zero-day attacks).
2. **Lớp máy chủ / Phân tích (Server / Forensics):** Sử dụng **Random Forest** (Học có giám sát) để phân loại chính xác các kịch bản tấn công (TH1–TH6) với độ chính xác cao (>98%).

---

## 🏗️ Kiến trúc hệ thống

```
+-----------------------------------------------------------+
|               Cụm thiết bị IoT (6 node ESP32)             |
|   esp32_01 .. esp32_06 gửi dữ liệu Telemetry qua MQTT     |
+-----------------------------+-----------------------------+
                              | Wi-Fi / MQTT
                              v
+-----------------------------------------------------------+
|          Edge Gateway (Raspberry Pi 5 / Wi-Fi AP)         |
|  - Thu gói mạng thời gian thực: Tshark / Pcapng           |
|  - Trích xuất 14 đặc trưng lưu lượng theo cửa sổ 5 giây   |
|  - Lớp 1: Isolation Forest (Học không giám sát)          |
+-----------------------------+-----------------------------+
                              | Báo cáo & Đặc trưng
                              v
+-----------------------------------------------------------+
|            Trung tâm Giám sát & Điều khiển (FastAPI)       |
|  - Lớp 2: Random Forest Binary & Scenario Classifier      |
|  - Quản lý cảnh báo, lưu trữ lịch sử sự cố (SQLite)       |
|  - Dashboard trực quan hóa 4 Tab (Vue.js + Tailwind CSS)   |
+-----------------------------------------------------------+
```

---

## 📂 Danh mục kịch bản thử nghiệm (TH0 – TH6)

* **TH0 (Normal):** Gửi bản tin định kỳ 2s (Bình thường).
* **TH1 (High Rate):** Tấn công dồn dập ~15 msg/s (Flooding / DoS).
* **TH2 (Large Payload):** Gói tin dung lượng bất thường ~1.5 KB.
* **TH3 (Reconnect):** Liên tục ngắt và tái kết nối MQTT mỗi 3s.
* **TH4 (Silence):** Node im lặng hoàn toàn / mất tín hiệu heartbeat.
* **TH5 (Burst Traffic):** Bắn lưu lượng xung nhịp ngắt quãng.
* **TH6 (Auth Fail):** Gửi sai thông tin đăng nhập xác thực MQTT.

---

## 🚀 Hướng dẫn cài đặt & Khởi chạy nhanh

### Yêu cầu môi trường
* Python 3.10+
* Các thư viện phụ thuộc: `pip install -r requirements.txt` (hoặc cài FastAPI, Uvicorn, Scikit-learn, Pandas, Joblib)

### Khởi chạy Dashboard cục bộ
```bash
# Cách 1: Chạy trực tiếp file bat
run_local.bat

# Cách 2: Chạy qua Python
python scripts/run_local.py
```
Sau đó truy cập giao diện giám sát tại: **http://127.0.0.1:8000**

---

## 📊 Cấu trúc thư mục

* `backend/`: Mã nguồn API FastAPI, kết nối Database SQLite và Web Dashboard tĩnh.
* `pipeline/`: Quy trình thu gói tin, trích xuất 14 đặc trưng lưu lượng và tiền xử lý dữ liệu.
* `models/`: Các mô hình học máy đã huấn luyện (Isolation Forest, Random Forest) và báo cáo đánh giá.
* `data/`: Dữ liệu thu thập (.pcapng), tập dữ liệu trích xuất và cơ sở dữ liệu hệ thống.
* `firmware/`: Mã nguồn PlatformIO / Arduino cho các node ESP32.
* `simulator/`: Kịch bản mô phỏng tấn công và phát lại gói tin mẫu.
* `docs/`: Báo cáo chi tiết và tài liệu kỹ thuật đề tài.
