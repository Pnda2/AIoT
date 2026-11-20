# TÀI LIỆU HƯỚNG DẪN BẢO VỆ VÀ BỘ CÂU HỎI PHẢN BIỆN
## ĐỀ TÀI: XÂY DỰNG HỆ THỐNG PHÁT HIỆN BẤT THƯỜNG TRONG LƯU LƯỢNG TRUYỀN THÔNG CỦA THIẾT BỊ IoT
- **Mã đề tài:** 12  
- **Kiến trúc:** Hybrid **Edge + Offline Training** (Raspberry Pi 5 Edge Gateway + PC Offline Trainer)  
- **Phần cứng & Giao thức:** Raspberry Pi 5, ESP32-S3, MQTT (`:1883`), Wi-Fi 2.4GHz, `dumpcap`/`tshark`  
- **Dữ liệu kiểm chứng:** CICIoT2023 Subset (`45` đặc trưng) & Dữ liệu thu thực tế ESP32-S3 (`14` đặc trưng, `2` đợt thu = `98` phút)

---

### PHẦN 1: KỊCH BẢN DEMO BẢO VỆ 8 – 10 PHÚT

| Thời gian | Màn hình thao tác | Thao tác thực tế | Điểm nhấn thuyết minh |
|---|---|---|---|
| **0 – 2 phút** | **Tổng quan & `Mô hình & Huấn luyện → CICIoT2023`** | Mở `http://192.168.137.35:8000`, vào tab `Mô hình & Huấn luyện` (mục `CICIoT2023`). | *"Hệ thống gồm 2 luồng tách biệt schema: Luồng 1 benchmark trên CICIoT2023 (16,350 mẫu, 45 đặc trưng, 34 lớp, chia 70/15/15 không rò rỉ dữ liệu). Trên 2,453 mẫu Test đóng băng, RF Binary đạt **95.84% Acc / 97.72% F1**, vượt qua Baseline Rule (90.98% F1). Bài toán 34 lớp được tách bảng riêng."* |
| **2 – 4 phút** | **`Mô hình & Huấn luyện → Local ESP32 (14 đặc trưng)`** | Bấm sub-tab `Local ESP32 (14 đặc trưng)` và lướt nhanh **Bước 1 → Bước 2 → Bước 3 & 4**. | *"Đây là dữ liệu thật thu 98 phút (2 đợt trên các board khác nhau: `esp32_06` & `esp32_05`), gom 58,373 gói `.pcapng` thành 1,667 cửa sổ 5s x 14 đặc trưng. Sau làm sạch (1,637 dòng) và Time-Based Split (Overlap = 0), **Isolation Forest** chỉ học TH0 đạt **96.02% Acc / 96.62% F1** (FPR 8.41%), **RF Binary 98.01% Acc / 98.28% F1** và **RF 7 kịch bản 98.01% Acc**."* |
| **4 – 5 phút** | **`Demo & Mô phỏng` (Replay + Simulator)** | Vào `Kiểm thử CICIoT2023` chọn `DDoS-SYN_Flood` bấm `Chạy kiểm thử`; chuyển sang `Mô phỏng 7 kịch bản` bấm `TH1`, `TH2`, `TH6`. | *"Kiểm chứng trực tiếp trên mẫu Hold-out Test thật chưa từng dùng train (hiển thị đủ 14 đặc trưng ESP32 và điểm Isolation Forest score âm sâu khi bất thường)."* |
| **5 – 7 phút** | **`Dữ liệu 5s` (`Cửa sổ 5s`, `Tshark`, `Log`)** | Mở tab `Dữ liệu 5s`, lướt qua `Cửa sổ 5 giây` (cột `SYN/FIN/RST`), `Gói tin Tshark & .pcapng`, và `Nhật ký trích xuất (Log)`. | *"Pi 5 bắt trực tiếp lưu lượng qua `tshark` trên `wlan0`, ghi `.pcapng` mở được bằng Wireshark, tính đồng nhất 14 đặc trưng mỗi 5s và lưu minh bạch toàn bộ log chạy live lẫn log làm sạch/train."* |
| **7 – 9 phút** | **`Live Hardware` (Trọng tâm thực nghiệm)** | Vào tab `Live Hardware`, bấm `TH1 Gói cao` hoặc `TH2 Gói lớn` trên 1 node đang Online -> quan sát biểu đồ & bảng cảnh báo -> trả lại `TH0 Bình thường`. Sau đó thử `TH4 Im lặng` đợi >8s. | *"Ngay trong cửa sổ 5s, biểu đồ vọt lên, `Isolation Forest` bắt bất thường còn `RF Scenario` gọi đúng tên kịch bản. Khi tắt tin ở TH4, **Watchdog Rule** phát hiện sau >8s và gắn nhãn rõ là Rule chứ không nhận vơ cho AI."* |

---

### PHẦN 2: BỘ CÂU HỎI PHẢN BIỆN & CÂU TRẢ LỜI MẪU (CẬP NHẬT)

#### 1. Tại sao phải tách riêng CICIoT2023 (45 đặc trưng) và Local ESP32 (14 đặc trưng), đồng thời tách bảng Binary và Multiclass?
> **Trả lời:**  
> - **Khác biệt schema & miền dữ liệu:** CICIoT2023 đo 45 đặc trưng luồng đa giao thức ở quy mô tấn công lab lớn; mạng ESP32 dùng MQTT trên Wi-Fi cục bộ nên 14 đặc trưng cửa sổ 5s (kể cả cờ `SYN/FIN/RST` và `is_empty_window`) mới phản ánh sát hành vi thật trên Pi 5.  
> - **Trung thực khi đánh giá:** Bài toán nhị phân (`2 lớp`: Normal vs Anomaly) và đa lớp (`34 lớp` CICIoT hoặc `7 kịch bản` ESP32) khác bản chất độ khó nên được tách riêng, cùng so sánh công bằng với **Baseline** (`Rule Threshold`, `Rule + Watchdog`, `Decision Tree nông`) trên cùng tập Test đóng băng.

#### 2. Tại sao chạy thực tế trên Pi 5 lại dùng `Isolation Forest` kết hợp `Random Forest Scenario`?
> **Trả lời:**  
> - **`Isolation Forest` (Unsupervised):** Chỉ cần học phân phối nền bình thường (`TH0`), giúp hệ thống vẫn phát hiện được kiểu bất thường mới chưa có trong tập mẫu; độ trễ suy luận trên Test chỉ **0.0247 ms/mẫu** (`F1 = 96.62%`, `Recall = 99.31%`).  
> - **`Random Forest Scenario`:** Khi đã phát hiện bất thường (`score < 0`), `RF Scenario` hỗ trợ gọi tên cụ thể kịch bản nghi ngờ (`TH1..TH6`, `Acc = 98.01%`) để người vận hành nhìn vào cảnh báo là biết ngay nguyên nhân (flood, payload lớn, reconnect hay sai mật khẩu).

#### 3. Làm sao tránh Data Leakage (rò rỉ dữ liệu) và tránh nhiễu mất pin khi thu thập từ ESP32?
> **Trả lời:**  
> 1. **Chống rò rỉ dữ liệu:** Toàn bộ `QuantileClipper (1%–99%)` và `RobustScaler` **chỉ `fit` trên tập Train (`70%`)** rồi `transform` sang Val (`15%`) và Test (`15%`). Đồng thời chia **Time-Based Split** tuần tự theo thời gian trong từng `(batch, kịch bản)` thay vì trộn ngẫu nhiên cửa sổ liền kề; kiểm tra hash các cửa sổ non-empty giữa Train và Test cho `overlap = 0`.  
> 2. **Lưu ý kỹ thuật với `Isolation Forest`:** Không gắn `QuantileClipper` học trên `TH0` vào pipeline `Isolation Forest`, vì clipper sẽ kẹp mất các giá trị gai bất thường ở Test về lại vùng an toàn của `TH0`.  
> 3. **Chống nhiễu mất pin/mạng khi thu thập:** Thu riêng từng phiên `TH0..TH6`, lọc gói theo IP thật từng board trong từng batch; các cửa sổ `0` gói trong `TH0` (`109` cửa sổ ở 2 đợt) được loại bỏ thay vì gán nhầm nhãn bình thường, trong khi `104` cửa sổ `0` gói của `TH4_Silence` được giữ nguyên để phản ánh đúng trạng thái im lặng.

#### 4. Vì sao cần thu 2 đợt (`batch_01` 40 phút trên `esp32_06` + `batch_02` 58 phút trên `esp32_05`)?
> **Trả lời:**  
> - Đợt 1 (`799` cửa sổ, `117` mẫu Test) mới chỉ có `9` mẫu Test mỗi kịch bản tấn công và mới quay trên 1 board (`esp32_06`), khiến `Isolation Forest` có `FPR = 17.46%`.  
> - Khi thu thêm đợt 2 (`58` phút) trên board khác (`esp32_05`) và gộp lại thành `1,667` cửa sổ (`251` mẫu Test — `24` mẫu Test cho mỗi kịch bản `TH1..TH6`), **FPR của `Isolation Forest` giảm hơn một nửa từ `17.46%` xuống `8.41%`**, `Accuracy` tăng từ **`89.74%` lên `96.02%`**, vượt cả 2 Baseline trên tập Test.

#### 5. Khi thiết bị ngừng gửi gói tin (TH4), tại sao vừa có mặt trong bộ 14 đặc trưng (`is_empty_window`), vừa dùng Watchdog Rule ngoài thực tế?
> **Trả lời:**  
> - Ở chế độ **chạy live trên Pi 5**, khi mạch sập nguồn quá 8 giây không tạo gói mới trong buffer, **Watchdog Rule** chủ động kích hoạt cảnh báo `SILENCE_TIMEOUT` đúng 1 lần khi mất kết nối mà không nhồi vector `0` giả tạo vào mô hình ML.  
> - Ở bộ **dataset 14 đặc trưng thu theo phiên cố định (`TH4_Silence`)**, cột `is_empty_window` ghi nhận trung thực tỷ lệ cửa sổ rỗng (`104/156` cửa sổ ở `TH4`, phần còn lại là gói MQTT keepalive `PINGREQ/PINGRESP`), giúp đánh giá tổng thể cả 7 tình huống trên cùng bảng benchmark.

---

### PHẦN 3: BẢNG TÓM TẮT SỐ LIỆU THỰC NGHIỆM (ĐỒNG BỘ TRÊN WEB & LOG)

| Hạng mục | Số liệu thực tế mới nhất |
|---|---|
| **CICIoT2023 (45 đt, 34 lớp)** | `16,350` mẫu (`11,445 Train / 2,452 Val / 2,453 Test`, `Overlap = 0`) |
| **CICIoT2023 Binary RF / IF / Rule** | RF `95.84% Acc / 97.72% F1` · IF `70.24% Acc / 80.51% F1 / FPR 4.44%` · Rule `90.98% F1` |
| **CICIoT2023 34 lớp** | RF Multiclass `22.83% Acc / 16.81% Macro F1` vs DT `d=6` `22.75% Acc / 12.72% Macro F1` |
| **Local ESP32 (`batch_01 + batch_02`)** | `98 phút` (`14` phiên `.pcapng`, `58,373` gói thô -> `1,667` cửa sổ -> `1,637` dòng sạch, `251 Test`) |
| **Local Binary (`Normal` vs `Anomaly`)** | **IF (Edge)** `96.02% Acc / 96.62% F1 / FPR 8.41%` · **RF Binary** `98.01% Acc / 98.28% F1 / FPR 3.74%` · Rule `91.11% F1` |
| **Local 7 kịch bản (`TH0–TH6`)** | **RF Scenario** `98.01% Acc / 98.18% Macro F1` vs DT `d=5` `95.62% Acc / 96.40% Macro F1` |
| **Tài nguyên trên Raspberry Pi 5** | CPU `0.9% – 7.0%`, RAM `12.8% – 13.6%`, `throttled=0x0`, artifacts `~11 MB` |
