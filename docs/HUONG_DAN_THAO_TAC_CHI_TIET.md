# HƯỚNG DẪN SỬ DỤNG & VẬN HÀNH CHI TIẾT HỆ THỐNG AIoT
**Web Dashboard:** `http://192.168.137.35:8000`  
**Gateway Raspberry Pi 5:** `pi@192.168.137.35` (`/home/pi/AIoT`)

Tài liệu này hướng dẫn đầy đủ từ cách bật/vận hành hệ thống hằng ngày, thao tác 4 tab Web Dashboard, xem log trên Terminal/Pi 5 (không cần Web), thu thập thêm dữ liệu multi-batch để train lại, đến cách nạp firmware nếu cần bổ sung thêm mạch ESP32-S3.

---

### PHẦN 1: KHỞI ĐỘNG HỆ THỐNG HẰNG NGÀY / KHI TRÌNH BÀY

#### Bước 1: Bật Wi-Fi Mobile Hotspot trên máy tính Windows
- Mở **Settings → Network & Internet → Mobile Hotspot** và bật **ON** (băng tần **2.4 GHz**):
  - **Tên mạng (SSID):** `phuanh`
  - **Mật khẩu:** `0123456789`

#### Bước 2: Cấp nguồn Raspberry Pi 5 và các mạch ESP32-S3
1. **Raspberry Pi 5:** Dùng nguồn Type-C chuẩn riêng (5V/3A–5A, tránh cắm nguồn Pi 5 từ cổng USB laptop để không sụt áp). Sau ~25–30s, Pi 5 tự vào Hotspot với IP `192.168.137.35` và 3 service nền (`mosquitto`, `iot_pipeline`, `iot_gateway`) tự khởi chạy qua `systemd`.
2. **Các node ESP32-S3:** Gắn chặt ăng-ten ngoài, cấp nguồn qua cổng USB máy tính (không nối chung nhiều node qua chia USB không nguồn rời) hoặc sạc điện thoại 5V. Sau ~10–15s các mạch tự kết nối MQTT gửi `TH0`.

#### Bước 3: Mở Web Dashboard trên trình duyệt
- Trên Chrome hoặc Microsoft Edge, truy cập đúng địa chỉ:  
  **`http://192.168.137.35:8000`** *(lưu ý dùng `http://`, không dùng `https://`; nhấn `Ctrl + F5` nếu vừa cập nhật giao diện)*.
- Hoặc mở nhanh từ PowerShell:
  ```powershell
  start http://192.168.137.35:8000
  ```

---

### PHẦN 2: HƯỚNG DẪN SỬ DỤNG 4 TAB TRÊN WEB DASHBOARD

#### Tab 1 — `Live Hardware` (Giám sát & Điều khiển mạch thật)
- **Thanh KPI đầu trang:** Theo dõi số node đang `online`, lưu lượng tức thời (`pkt/s`, `B/s`), trạng thái mạng (`Bình thường` / `Phát hiện bất thường`) và số cảnh báo trong 5 phút gần nhất.
- **Hai biểu đồ trực tiếp:** Biểu đồ đường `Tốc độ gói tin theo thời gian (pkt/s)` theo dõi từng node theo cửa sổ 5s; biểu đồ cột ngang `Lưu lượng từng Node (B/s)` giúp phát hiện ngay gói payload lớn (`TH2`).
- **Thẻ điều khiển 6 node (`ESP32-S3 Node 1 → Node 6`):** Hiển thị IP thật của board (do `tshark` bắt tự động), kịch bản hiện tại và 6 nút gửi lệnh MQTT trực tiếp: `TH0 Bình thường`, `TH1 Gói cao`, `TH2 Gói lớn`, `TH3 Ngắt nối`, `TH5 Burst`, `TH4 Im lặng`.
- **Bảng `Lịch sử cảnh báo gần đây`:** Phân tách rõ nguồn gốc phát hiện gồm **`Isolation Forest`** (kèm kịch bản dự đoán từ `RF Scenario`), **`Tshark`** (`RECONNECT_STORM`, `AUTH_FAILURE`) và **`Watchdog`** (`SILENCE_TIMEOUT > 8s`).

#### Tab 2 — `Dữ liệu 5s` (Cửa sổ đặc trưng, Tshark, Log & Xuất CSV)
- **`Cửa sổ 5 giây`:** Bảng dữ liệu live trích xuất mỗi 5s (Số gói, Tổng Bytes, TB độ dài, Mean IAT, Packet Rate, Byte Rate và 3 cờ `SYN / FIN / RST`).
- **`Gói tin Tshark & .pcapng`:** Xem từng frame bắt trực tiếp từ `wlan0` cổng `1883` và bấm vào tên file `mqtt_lab_*.pcapng` để tải file thô mở trực tiếp trên **Wireshark**.
- **`Nhật ký trích xuất (Log)`:** Chọn xem ngay tại chỗ **4 nguồn log**:
  1. `Pi 5 Live 5s ([WINDOW #N])` — stream log trích xuất & suy luận 5s đang chạy thật trên Pi 5.
  2. `Trích xuất 14đt (extract_features.log)` — toàn bộ bước gộp 14 phiên `.pcapng` thành 1,667 cửa sổ.
  3. `Làm sạch & Train Local (train_local.log)` — toàn bộ bước làm sạch, chia tập 70/15/15, Baseline và đánh giá Test.
  4. `Train CICIoT2023 (train_ciciot.log)` — log chuẩn hóa và đánh giá bộ CICIoT2023.
  *(Có kèm nút tải thẳng file `.log` qua API `/api/logs/files/{filename}`).*
- **`Xuất CSV (5s)` & `Dataset 14đt`:** Tải nhanh dữ liệu cửa sổ live từ SQLite hoặc tải bộ [local_feature_windows.csv](file:///C:/TaiLieu/AIoT/data/processed/local_feature_windows.csv) (`1,667` dòng x `20` cột).

#### Tab 3 — `Demo & Mô phỏng`
- **`Kiểm thử CICIoT2023`:** Chọn một nhãn trong `34` lớp và 1 trong 3 mô hình (`RF Binary`, `RF 34 lớp`, `Isolation Forest`) để chạy kiểm thử trên mẫu hold-out chưa dùng để train (tự loại trường nhãn trước khi suy luận).
- **`Mô phỏng 7 kịch bản (TH0–TH6)`:** Bấm từng kịch bản `TH0..TH6` để kiểm tra phản ứng của `Isolation Forest` (`v2_14features`) + `RF Scenario` trên mẫu hold-out Test thật từ ESP32 (`Dữ liệu Hold-out Test thật từ ESP32`), xem điểm `Anomaly Score` (thước đo ±0.35) và toàn bộ **14 đặc trưng** đầu vào.

#### Tab 4 — `Mô hình & Huấn luyện`
Chia làm 2 sub-tab độc lập, không đánh giá chéo bài toán khác mục tiêu:
- **`CICIoT2023 (45 đặc trưng)`:** Hiển thị KPI 16,350 mẫu, khối làm sạch & `QuantileClipper`/`RobustScaler` fit trên Train (`Overlap = 0`), biểu đồ đối chuẩn Nhóm 1 (`Rule` / `DT d=3` / `Isolation Forest` / `RF Binary`), ma trận nhầm lẫn, khối đánh giá độc lập 34 lớp (Nhóm 2) và Console Log.
- **`Local ESP32 (14 đặc trưng)`:** Hiển thị đúng trình tự khoa học từ trên xuống dưới:
  - KPI tổng kết (`1,637` mẫu sạch, `14` cột, Edge `IF F1 96.62% / FPR 8.41%`, `RF 7 kịch bản Acc 98.01%`).
  - **Bước 1:** Bảng 14 phiên `.pcapng` (`batch_01` + `batch_02`, `58,373` gói thô, cơ chế lọc chống nhiễu mất kết nối tạm).
  - **Bước 2:** Quy trình Làm sạch, Chia tập Time-Based Split `70% / 15% / 15%` từng `(batch, kịch bản)` và bảng phân bố mẫu từng kịch bản.
  - **Bước 3 & 4:** Bảng đối chuẩn Baseline vs Mô hình chính (`Accuracy`, `Precision`, `Recall`, `F1/Macro F1`, `FPR`, `Latency`), độ chính xác chi tiết từng kịch bản trên `251` mẫu Test, ma trận nhầm lẫn và Console Log (`extract_features.log`, `train_local.log`).

---

### PHẦN 3: XEM LOG TRÊN TERMINAL (KHÔNG CẦN MỞ WEB)

#### 1. Trên PC (`C:\TaiLieu\AIoT`) bằng PowerShell
- **Xem nguyên văn log đã chạy (không phải chờ train lại):**
  ```powershell
  Get-Content C:\TaiLieu\AIoT\logs\extract_features.log -Encoding UTF8
  Get-Content C:\TaiLieu\AIoT\logs\train_local.log -Encoding UTF8
  Get-Content C:\TaiLieu\AIoT\logs\train_ciciot.log -Encoding UTF8
  ```
- **Hoặc chạy trực tiếp script trên PC để quan sát từng bước trên Terminal:**
  ```powershell
  python pipeline\extract_features.py
  python models\training\train_local.py
  python models\training\train_ciciot.py
  ```

#### 2. Trực tiếp từ Raspberry Pi 5 qua SSH
> Lưu ý: Hai dịch vụ `iot_pipeline` và `iot_gateway` ghi log trực tiếp vào `/home/pi/AIoT/pipeline.log` và `/home/pi/AIoT/backend.log` chứ không đẩy vào `journald`.

```powershell
# Xem log thu thập & trích xuất 5s chạy live trên Pi 5 (cứ 5s nhảy 1 khối [WINDOW #N], Ctrl+C để thoát):
ssh pi@192.168.137.35 "tail -n 30 -f /home/pi/AIoT/pipeline.log"

# Xem log Web API Gateway trên Pi 5:
ssh pi@192.168.137.35 "tail -n 30 -f /home/pi/AIoT/backend.log"

# Xem log làm sạch, chia tập & huấn luyện đang lưu trên Pi 5:
ssh pi@192.168.137.35 "cat /home/pi/AIoT/logs/extract_features.log"
ssh pi@192.168.137.35 "cat /home/pi/AIoT/logs/train_local.log"
ssh pi@192.168.137.35 "cat /home/pi/AIoT/logs/train_ciciot.log"

# Kiểm tra dịch vụ nền, nguồn điện & dung lượng thẻ nhớ Pi 5:
ssh pi@192.168.137.35 "vcgencmd get_throttled; df -h /; systemctl is-active mosquitto iot_pipeline iot_gateway"
```

---

### PHẦN 4: QUY TRÌNH THU THÊM ĐỢT DỮ LIỆU MỚI (MULTI-BATCH), TRAIN LẠI & DEPLOY

Khi muốn thu thêm một đợt mới (`batch_03`...) từ các mạch ESP32 mà vẫn giữ nguyên `batch_01`, `batch_02`:
1. **Chạy thu 7 phiên trên Pi 5 (tự động ghi sang thư mục `batch_XX` mới và tự khôi phục dịch vụ khi xong):**
   ```powershell
   ssh pi@192.168.137.35 "python3 -u /home/pi/AIoT/scripts/collect_sessions.py --batch auto --th0-mins 10 --attack-mins 5"
   ```
   *(Nếu có thử `TH6_AuthFail`, ngay sau khi hoàn tất cần bấm nút **`RST`** 1 lần — hoặc rút cắm nguồn — trên node được chọn chạy tấn công để thoát vòng lặp sai mật khẩu trong [main.cpp](file:///C:/TaiLieu/AIoT/firmware/src/main.cpp#L149-L175)).*
2. **Kéo batch mới về PC (`data/sessions/`), trích xuất gộp & train lại:**
   ```powershell
   scp -r pi@192.168.137.35:/home/pi/AIoT/data/sessions/batch_03 C:\TaiLieu\AIoT\data\sessions\
   python pipeline\extract_features.py
   python models\training\train_local.py
   ```
3. **Đẩy model `.joblib`, dataset CSV, báo cáo JSON và `.log` xuống Pi 5:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\deploy_to_pi5.ps1
   ```

---

### PHẦN 5: LƯU Ý NẠP FIRMWARE KHI BỔ SUNG / THAY THẾ BOARD ESP32-S3

- Toàn bộ board dùng chung mã nguồn [main.cpp](file:///C:/TaiLieu/AIoT/firmware/src/main.cpp). Khi nạp cho board số nào thì đổi đúng `#define NODE_ID X` (`1..6`) ở đầu file để tránh trùng `client_id` làm đá phiên MQTT của board khác.
- Sau khi nạp qua PlatformIO (`pio run -t upload`) hoặc Arduino IDE (`ESP32S3 Dev Module`), bấm `RST` để board vào mạng `phuanh` và gửi `TH0` tự động.
- Các bản sao lưu dự phòng trên PC hiện có tại `C:\TaiLieu\AIoT_backup_20261111` và `C:\TaiLieu\AIoT_backup_before_tshark`.
