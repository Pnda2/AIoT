# BÁO CÁO MÔ TẢ CHI TIẾT DỰ ÁN & KẾT QUẢ THỰC NGHIỆM
## ĐỀ TÀI: XÂY DỰNG HỆ THỐNG PHÁT HIỆN BẤT THƯỜNG TRONG LƯU LƯỢNG TRUYỀN THÔNG CỦA THIẾT BỊ IoT
- **Mã đề tài:** 12  
- **Kiến trúc triển khai:** Hybrid **Edge + Offline Training** (Raspberry Pi 5 xử lý biên 24/7 + PC huấn luyện/kiểm định ngoại tuyến)  
- **Nền tảng phần cứng:** Raspberry Pi 5 (8GB RAM, IP `192.168.137.35`) + các node phần cứng **ESP32-S3** (Wi-Fi Hotspot `phuanh`)  
- **Cập nhật phiên bản:** 11/2026 (`v2_14features` — đồng bộ 14 đặc trưng Tshark/Wire cho cả thu thập `.pcapng` và suy luận live)

---

### I. TỔNG QUAN KIẾN TRÚC HỆ THỐNG

Hệ thống phân tách rạch ròi vai trò giữa **thiết bị biên (Edge Pi 5)** và **máy trạm huấn luyện (PC)** để vừa đảm bảo chạy thực tế nhẹ, liên tục 24/7 trên Pi 5, vừa hiển thị minh bạch toàn bộ quy trình làm sạch, chia tập chống rò rỉ dữ liệu và đánh giá mô hình:

1. **Lớp thiết bị IoT (ESP32-S3 Nodes — Firmware [main.cpp](file:///C:/TaiLieu/AIoT/firmware/src/main.cpp)):**
   - Gồm tối đa 6 node `esp32_01` → `esp32_06` kết nối Wi-Fi `phuanh` (`192.168.137.x`), giao tiếp qua MQTT Port `1883`.
   - Hỗ trợ 7 kịch bản lưu lượng thật (`TH0` Bình thường mỗi 2s, `TH1` High Rate ~15 msg/s, `TH2` Large Payload ~1.5 KB, `TH3` Reconnect Loop 3s, `TH4` Silence, `TH5` Burst 20 gói theo đợt, `TH6` Auth Fail thử sai User/Pass MQTT), điều khiển qua nút `BOOT` cứng trên mạch hoặc lệnh MQTT `wievac/control/<device_id>`.
2. **Lớp xử lý biên 24/7 trên Raspberry Pi 5:**
   - **`mosquitto.service` (Port `1883`):** Broker MQTT trung tâm.
   - **`iot_pipeline.service` ([feature_extractor.py](file:///C:/TaiLieu/AIoT/pipeline/feature_extractor.py) + [tshark_collector.py](file:///C:/TaiLieu/AIoT/pipeline/tshark_collector.py)):**
     - `dumpcap` + `tshark` bắt trực tiếp toàn bộ frame TCP/MQTT cổng `1883` trên card `wlan0`, lưu file `.pcapng` xoay vòng tại `/home/pi/AIoT/data/local_captures/` (tối đa 5 file × 512 KB) và tự phân giải IP thật của từng ESP32.
     - Mỗi cửa sổ **5.0 giây** tính **14 đặc trưng** chuẩn ([window_features.py](file:///C:/TaiLieu/AIoT/pipeline/window_features.py)), chạy song song **Isolation Forest (phát hiện dị thường chưa biết trước)**, **Random Forest Scenario (định danh kịch bản `TH0..TH6`)**, **Tshark Network Rule (`RECONNECT_STORM`, `AUTH_FAILURE`)** và **Watchdog Rule (`SILENCE_TIMEOUT > 8s`)**.
     - Ghi log từng chu kỳ `[WINDOW #N]` vào `/home/pi/AIoT/pipeline.log` và bảng `system_events` trong SQLite (`/home/pi/AIoT/data/iot_system.db`).
   - **`iot_gateway.service` ([main.py](file:///C:/TaiLieu/AIoT/backend/app/main.py) + [index.html](file:///C:/TaiLieu/AIoT/backend/static/index.html)):** Web Server FastAPI + Uvicorn mở cổng `:8000` (`http://192.168.137.35:8000`), phục vụ Dashboard 4 tab trên giao diện web và API REST.
3. **Lớp huấn luyện ngoại tuyến & triển khai tự động trên PC:**
   - Kéo các phiên `.pcapng` thu tự động từ Pi 5 về PC, chạy [extract_features.py](file:///C:/TaiLieu/AIoT/pipeline/extract_features.py) → [train_local.py](file:///C:/TaiLieu/AIoT/models/training/train_local.py) → đóng gói toàn bộ model nén `.joblib`, dataset CSV, báo cáo JSON và file `.log` đẩy ngược xuống Pi 5 qua [deploy_to_pi5.ps1](file:///C:/TaiLieu/AIoT/scripts/deploy_to_pi5.ps1).

---

### II. BỘ 14 ĐẶC TRƯNG CỬA SỔ 5 GIÂY (`v2_14features`)

Áp dụng thống nhất 100% giữa quá trình trích xuất offline `.pcapng` ([extract_features.py](file:///C:/TaiLieu/AIoT/pipeline/extract_features.py)) và quá trình bắt gói live `tshark` trên Pi 5 ([window_features.py](file:///C:/TaiLieu/AIoT/pipeline/window_features.py)):

| STT | Tên đặc trưng | Mô tả kỹ thuật | Ý nghĩa phát hiện |
|---:|---|---|---|
| 1 | `packet_count` | Tổng số gói TCP/MQTT cổng `1883` trong 5s | Phát hiện High Rate (`TH1`), Burst (`TH5`), Silence (`TH4`) |
| 2 | `byte_count` | Tổng dung lượng frame (bytes) trong 5s | Phát hiện băng thông bất thường (`TH1`, `TH2`) |
| 3 | `packet_rate` | `packet_count / 5.0` (gói/giây) | Tốc độ gửi gói trung bình |
| 4 | `byte_rate` | `byte_count / 5.0` (bytes/giây) | Băng thông trung bình |
| 5 | `len_mean` | Độ dài gói trung bình (bytes) | Phát hiện Payload lớn (`TH2`, ~644 B vs ~101 B của `TH0`) |
| 6 | `len_std` | Độ lệch chuẩn kích thước gói (bytes) | Phân biệt gói đều đặn hay pha trộn padding/ACK |
| 7 | `len_max` | Kích thước gói lớn nhất trong cửa sổ (bytes) | Bắt đỉnh kích thước gói payload (`TH2`) |
| 8 | `iat_mean` | Khoảng cách thời gian trung bình giữa 2 gói liên tiếp (ms) | Giảm mạnh khi flood (`~32 ms` ở `TH1` so với `~646 ms` ở `TH0`) |
| 9 | `iat_std` | Độ lệch chuẩn IAT (ms) | Phản ánh độ giật/dồn cụm (`TH5 Burst`) |
| 10 | `iat_max` | Khoảng thời gian gián đoạn lớn nhất (ms) | Phát hiện nhịp nghỉ giữa các đợt xả burst |
| 11 | `tcp_syn_count` | Số gói có cờ `SYN` | Phát hiện thiết lập lại TCP liên tục (`TH3`, `TH6`) |
| 12 | `tcp_fin_count` | Số gói có cờ `FIN` | Phát hiện đóng phiên đột ngột (`TH3`, `TH6`) |
| 13 | `tcp_rst_count` | Số gói có cờ `RST` | Phát hiện từ chối/reset kết nối (`TH6`, nghẽn socket) |
| 14 | `is_empty_window` | Cờ nhị phân `1` nếu cửa sổ có `0` gói (`0` nếu có gói) | Xử lý trung thực kịch bản `TH4 Silence` trong dataset |

---

### III. QUY TRÌNH DỮ LIỆU & KẾT QUẢ THỰC NGHIỆM (ĐÃ KIỂM ĐỊNH)

Hệ thống đánh giá độc lập 2 bộ dữ liệu, tuyệt đối **không trộn schema** và **không so sánh gộp chung bài toán nhị phân với đa lớp**.

#### 1. Luồng Offline Benchmark: CICIoT2023 Subset (`45 đặc trưng`, `34 lớp`)
- **Dữ liệu & Tiền xử lý ([train_ciciot.py](file:///C:/TaiLieu/AIoT/models/training/train_ciciot.py)):** `16,350` mẫu (`0` NaN/Inf, `0` dòng trùng) -> chia Stratified **70% Train (`11,445`) / 15% Val (`2,452`) / 15% Test đóng băng (`2,453`)**, trùng lặp Train–Test = **`0` mẫu**. `QuantileClipper (1%–99%)` + `RobustScaler` chỉ fit trên Train (chú ý: pipeline `Isolation Forest` không gắn `QuantileClipper` của riêng Benign để tránh cắt nhầm gai tấn công về vùng an toàn).
- **Nhóm 1 — Phát hiện bất thường (`BenignTraffic` vs `Attack`) trên Test (`2,453` mẫu):**

| Mô hình | Accuracy | Precision | Recall | F1-Score | FPR (Báo sai) | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Rule Threshold (Baseline Q99) | 84.96% | 99.89% | 83.53% | 90.98% | 0.89% | 0.0004 ms |
| Decision Tree `d=3` (Baseline ML) | 95.19% | 97.39% | 97.31% | 97.35% | 25.78% | 0.0004 ms |
| Isolation Forest *(chỉ học Benign)* | 70.24% | 99.34% | 67.68% | 80.51% | 4.44% | 0.0064 ms |
| **Random Forest Binary** | **95.84%** | **97.46%** | **97.98%** | **97.72%** | **25.33%** | **0.0106 ms** |

*(Ma trận nhầm lẫn RF Binary trên Test: `True Benign = 168`, `False Alarm = 57`, `Missed Attack = 45`, `True Attack = 2,183`).*

- **Nhóm 2 — Phân loại sâu `34` lớp (đánh giá độc lập):**
  - Decision Tree `d=6` (Baseline): `Accuracy = 22.75%`, `Macro F1 = 12.72%` (`0.0004 ms`)
  - **Random Forest Multiclass (34 lớp):** `Accuracy = 22.83%`, `Macro F1 = 16.81%` (`0.0103 ms`)

#### 2. Luồng Thực nghiệm Phần cứng ESP32-S3 (`14 đặc trưng`, `7 kịch bản TH0–TH6`)
- **Thu thập thực tế 2 đợt (98 phút, `0` gói rớt trên `dumpcap wlan0`):**
  - **`batch_01` (40 phút — node `esp32_06` tấn công):** `23,210` gói thô -> `799` cửa sổ (`439 Normal` từ 4 node + `60/kịch bản` `TH1..TH6`).
  - **`batch_02` (58 phút — node `esp32_05` tấn công):** `35,163` gói thô -> `868` cửa sổ (`292 Normal` từ 3 node + `96/kịch bản` `TH1..TH6`).
  - **Tổng gộp (`14` phiên thu):** `58,373` gói thô -> **`1,667` cửa sổ** (`731 Normal | 936 Anomaly`). Cơ chế lọc tự động loại `109` cửa sổ rỗng ở `TH0` (tránh nhiễu khi node chập chờn Wi-Fi/nguồn) và giữ nguyên `104` cửa sổ rỗng thuộc `TH4_Silence`.
- **Làm sạch & Chia tập Time-Based Split ([train_local.py](file:///C:/TaiLieu/AIoT/models/training/train_local.py)):**
  - `0` ô NaN/±Inf; loại `30` mẫu non-empty trùng lặp (giữ nguyên `104` dòng im lặng `TH4`) -> **`1,637` dòng sạch**.
  - Chia tuần tự theo thời gian trong từng `(batch, kịch bản)` (`70% / 15% / 15%`): **`1,144 Train` (`492 Normal | 652 Anomaly`) / `242 Val` / `251 Test đóng băng`**, trùng lặp non-empty Train–Test = **`0` mẫu**.
- **Nhóm 1 — Phát hiện bất thường ESP32 (`0=Normal` vs `1=Anomaly`) trên Test (`251` mẫu: `107 Normal | 144 Anomaly`):**

| Mô hình | Accuracy | Precision | Recall | F1-Score | FPR (Báo sai) | Latency |
|---|---:|---:|---:|---:|---:|---:|
| Rule + Watchdog (Baseline) | 90.44% | 97.62% | 85.42% | 91.11% | 2.80% | 0.0000 ms |
| Decision Tree `d=3` (Baseline ML) | 95.62% | 94.04% | 98.61% | 96.27% | 8.41% | 0.0000 ms |
| **Isolation Forest (Pi 5 Edge)** | **96.02%** | **94.08%** | **99.31%** | **96.62%** | **8.41%** | **0.0247 ms** |
| **Random Forest Binary** | **98.01%** | **97.28%** | **99.31%** | **98.28%** | **3.74%** | **0.1044 ms** |

*(Ma trận nhầm lẫn trên 251 mẫu Test: `Isolation Forest` đạt `TN=98, FP=9, FN=1, TP=143`; `RF Binary` đạt `TN=103, FP=4, FN=1, TP=143`).*

- **Nhóm 2 — Nhận diện 7 kịch bản (`TH0..TH6`) trên Test (`251` mẫu):**
  - Decision Tree `d=5` (Baseline): `Accuracy = 95.62%`, `Macro F1 = 96.40%` (`0.0060 ms`)
  - **Random Forest Scenario (7 kịch bản):** `Accuracy = 98.01%`, `Macro F1 = 98.18%` (`0.1044 ms`)
- **Độ chính xác chi tiết từng kịch bản trên Test (`251` mẫu):**
  - `auth_fail` (`24` mẫu), `high_rate` (`24` mẫu), `large_payload` (`24` mẫu), `reconnect` (`24` mẫu), `silence` (`24` mẫu): đạt **100.00%** ở cả `Isolation Forest`, `RF Binary` và `RF Scenario`.
  - `burst` (`24` mẫu): `Isolation Forest` & `RF Binary` bắt đạt **95.83%** (`23/24`), `RF Scenario` đúng **91.67%** (1 cửa sổ rơi vào quãng nghỉ 5s giữa hai đợt burst).
  - `normal` (`107` mẫu): `Isolation Forest` báo nhầm `8.41%` (`9/107`), `RF Binary` báo nhầm `3.74%` (`4/107`), `RF Scenario` đúng **97.20%**.

---

### IV. TÀI NGUYÊN HỆ THỐNG & KẾT LUẬN

- **Hiệu năng đo thực tế trên Raspberry Pi 5:** CPU `~0.9% – 7.0%`, RAM `~12.8% – 13.6%`, `vcgencmd get_throttled = 0x0`, bộ artifacts đã nén (`10` file trong `/home/pi/AIoT/models/artifacts/`) gọn chỉ **`~11 MB`**.
- **Hệ thống hoàn chỉnh:** Đáp ứng trọn vẹn từ phần cứng thật (`ESP32-S3 + Pi 5 + Wireshark/tshark`), pipeline dữ liệu sạch chống rò rỉ đa batch (`1,667` cửa sổ thực tế), đối chuẩn minh bạch với Baseline, đến Web Dashboard 4 tab (`http://192.168.137.35:8000`) và bộ file log đầy đủ trên cả PC lẫn Pi 5.
