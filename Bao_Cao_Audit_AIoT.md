# Báo cáo audit và kiểm thử hệ thống phát hiện bất thường IoT

**Đề tài 12 · Raspberry Pi 5 Edge và huấn luyện offline trên PC**  
**Ngày audit** 19/11/2026, giờ Việt Nam  
**Thư mục dự án** `C:\TaiLieu\AIoT`

## Kết luận nghiệm thu

**Chưa đủ điều kiện nghiệm thu theo phạm vi cập nhật.** Hai benchmark chạy lại được và các model 45/14 đặc trưng được tách riêng. Có ba sai lệch nghiêm trọng cần sửa trước khi trình bày kết quả trước Hội đồng: dashboard Live tô cảnh báo từ kịch bản được chọn, Demo Lab trả score hoặc nhãn dưới tên mô hình mà có trường hợp không hề suy luận, và tập Test Local dùng lại toàn bộ 14 phiên đã có trong Train. Bản chạy kiểm tra lần này xác minh được luồng PCAPNG → CSV → huấn luyện → artifact → API trên Windows và logic Vue qua Node. Phần Pi 5/ESP32, Mosquitto đầu cuối và thời gian cảnh báo trên phần cứng còn chờ nghiệm thu.

**Căn cứ** `Prompt_IoT.docx` mục 4–6 và checklist cuối, `Phan_Bo_Sung_DeTai_IoT.docx` mục 11–16, `docs/BAO_CAO_CHI_TIET_DU_AN.md`, hai hướng dẫn Markdown, hướng dẫn vận hành Word, mã và dữ liệu trong thư mục dự án. Tài liệu bổ sung được dùng để giải quyết khác biệt về số lượng và mục đích giao diện. Số dòng dưới đây tham chiếu file gốc. Đợt audit đọc mã ứng dụng, cấu hình triển khai, hai CSV, 14 capture, hai manifest, SQLite, sáu model, năm JSON báo cáo/mẫu, ba log và các tài liệu kỹ thuật. Build cache và mã thư viện PlatformIO đi kèm được xem là dependency, phạm vi rà soát mã nguồn tập trung vào mã do dự án vận hành. Các phép thử tạo/ghi dữ liệu thực hiện với bản sao hoặc dữ liệu tạm. Lần gọi TestClient đầu tiên đã import backend trong thư mục gốc và chạy hàm khởi tạo SQLite trước khi bị kẹt ở runtime Windows. Mốc sửa và kích thước DB gốc giữ nguyên khi kiểm tra, và các phép thử tiếp theo dùng DB sao chép.

## 1. Bám sát mục tiêu và phạm vi

### Chấm điểm theo bằng chứng

Mỗi nhóm được chấm theo mức đáp ứng và xác minh được trong đợt audit. Trọng số do người audit đề xuất vì báo cáo cần tách hai bộ yêu cầu và hai tài liệu mô tả tiêu chí nghiệm thu bằng nội dung, không quy định cách tính phần trăm dưới đây. Điểm dùng để ưu tiên sửa, giới hạn phần cứng chưa xác minh ảnh hưởng điểm nhóm Live và kiểm thử. Ba lỗi CRITICAL chặn nghiệm thu kể cả khi điểm tổng tăng.

| Nhóm | Prompt ban đầu | Phần bổ sung | Căn cứ chính |
|---|---:|---:|---|
| Kiến trúc PC/Pi, hai nguồn dữ liệu và schema | 16/20 | 9/10 | Hai pipeline và sáu artifact chạy được. Capture/config còn phụ thuộc môi trường lab |
| Phương pháp ML và khả năng tái lập | 18/25 | 12/20 | Tái lập metric, preprocessing fit trên Train. Split Local dùng chung phiên, provenance CIC giới hạn |
| Giao diện, dữ liệu và demo | 11/15 | 15/25 | Bốn mục điều hướng, replay, báo cáo và log có sẵn. Thiếu workflow nghiên cứu, quản lý phiên và lịch sử demo |
| Live, quy tắc và trung thực | 8/20 | 14/30 | Có code capture, IF, rule. Hiển thị suy diễn từ nút và giả lập score. Bằng chứng phần cứng chưa đủ |
| Kiểm thử, tự động hóa, phục hồi và hồ sơ nghiệm thu | 8/20 | 7/15 | Thiếu soak test, health thực, lock handling, bản cài được khóa phiên bản và hồ sơ đo Pi |
| **Tổng** | **61/100** | **57/100** | **Chưa đạt nghiệm thu** |

### Ánh xạ bốn giao diện

| Giao diện theo mục 12 tài liệu bổ sung | Giao diện thực tế | Đánh giá |
|---|---|---|
| 01 CICIoT2023 Lab | Mô hình & Huấn luyện → CICIoT2023 | Có thống kê artifact, baseline, RF, IF, ma trận nhị phân. Chưa có nạp/kiểm schema CSV, phân bố thực theo lớp trên UI, chọn subset và chạy huấn luyện/đánh giá từ Lab. Các thao tác huấn luyện hiện là CLI |
| 02 Local Dataset | Dữ liệu 5s và một phần Mô hình & Huấn luyện → Local ESP32 | Mục Dữ liệu 5s ưu tiên dữ liệu Live và log. Báo cáo phiên nằm ở mục mô hình. API preview CSV có nhưng UI không gọi. Thiếu quản lý/import phiên và bảng đối chiếu nhãn với dự đoán từng cửa sổ |
| 03 Demo Lab | Demo & Mô phỏng → CIC replay và TH0–TH6 | Hai nhánh tồn tại, gọi đúng API. Nhánh Local mặc định lấy lại Test nếu có mẫu rồi mới dùng vector kịch bản. Thiếu chế độ chọn tách rõ, số mẫu CIC, lịch sử, định danh mẫu, phiên bản model và latency Local |
| 04 Live Hardware | Live Hardware | Có trạng thái, biểu đồ, gói lệnh, cảnh báo. UI và DB cố định sáu node so với bốn node của tài liệu. Thiếu xác nhận lệnh từ node, trạng thái capture thật, nguồn hardware/simulator và bằng chứng liên kết từ alert về window |

Bằng chứng điều hướng tại `backend/static/index.html:57–67,255–266,439–446,603–620`. Phần quản lý mặc định sáu node tại `backend/app/db/database.py:105–119`, `pipeline/feature_extractor.py:20–33` và `backend/static/index.html:1425–1508`. Nếu sáu board là phạm vi mở rộng đã thống nhất, tài liệu nghiệm thu cần ghi rõ và UI nên đọc danh sách thiết bị từ cấu hình.

### Trung thực và tách bài toán

- **Ground truth và Prediction** tách trường tại `backend/app/main.py:156–166,247–256` và tách vùng UI tại `backend/static/index.html:497–515,559–570`. Với Live, `scenario_label` lưu vào JSON cửa sổ từ trạng thái thiết bị trong DB, trong khi chính API control cập nhật trạng thái ngay khi gửi lệnh. Trường này chỉ đủ gọi là kịch bản yêu cầu/báo cáo cho đến khi có xác nhận và mốc hiệu lực. Bảng cửa sổ thiếu cặp Ground Truth/Prediction.
- **Định danh** CSV Local có `device_key` và `batch` phục vụ truy vết. X chỉ lấy danh sách 14 đặc trưng trong `models/training/train_local.py:153–170` và `pipeline/feature_extractor.py:264–287`. Trong CSV CIC có sẵn, 45 cột hành vi không gồm IP, MAC, ID. Tuy nhiên `train_ciciot.py:43–55` chọn toàn bộ cột trừ `label`. Nếu thay CSV có cột định danh hoặc timestamp, bộ train có thể nhận nhầm. Nên khóa danh sách đặc trưng và reject schema ngoài hợp đồng.
- **Hai nguồn và hai bài toán** kiểm tra đủ sáu model. CIC gồm IF 45 đặc trưng, RF Binary 45, RF Multiclass 34 lớp/45. Local gồm IF 14, RF Binary 14, RF Scenario 7 lớp/14. IF chỉ giải bài toán normal/anomaly. RF Binary Local là đối chứng offline, runtime hiện dùng Local IF và RF Scenario. Khi deploy cần kiểm cả tên, thứ tự, kiểu, nguồn feature và phiên bản model, vì kiểm mỗi chiều vector không phát hiện schema lệch thứ tự.

## 2. Dữ liệu, ML và quy tắc phát hiện

### Kết quả tái lập trên PC

| Dữ liệu | Quy mô | Chia Train / Val / Test | Hash Train–Test |
|---|---|---|---|
| CIC subset | 16.350 dòng, 45 đặc trưng, 34 lớp. Benign 1.500 và 33 lớp còn lại 450 dòng/lớp | 11.445 / 2.452 / 2.453, stratified theo lớp, seed 42 | 0 hash trùng |
| Local ESP32 | 58.373 gói cổng 1883 từ 14 PCAPNG, 2 batch, 98 phút. Trích lại 1.667 cửa sổ gồm 731 normal và 936 bất thường theo nhãn phiên. CSV sinh lại giống tệp gốc từng byte | Sau làm sạch 1.637 dòng, chia 1.144 / 242 / 251 | 0 hash trùng non-empty, **14/14 phiên xuất hiện ở cả Train và Test** |

| Bài toán | Mô hình | Accuracy | F1 hoặc Macro-F1 | FPR |
|---|---|---:|---:|---:|
| CIC nhị phân | Rule Threshold | 84,96% | 90,98% | 0,89% |
| CIC nhị phân | DT d=3 | 95,19% | 97,35% | 25,78% |
| CIC nhị phân | Isolation Forest | 70,24% | 80,51% | 4,44% |
| CIC nhị phân | RF Binary | 95,84% | 97,72% | 25,33% |
| CIC 34 lớp | DT d=6 / RF | 22,75% / 22,83% | 12,72% / 16,81% macro | — |
| Local nhị phân, split nội phiên | Rule + empty-window baseline | 90,44% | 91,11% | 2,80% |
| Local nhị phân, split nội phiên | DT d=3 | 95,62% | 96,27% | 8,41% |
| Local nhị phân, split nội phiên | Isolation Forest | 96,02% | 96,62% | 8,41% |
| Local nhị phân, split nội phiên | RF Binary | 98,01% | 98,28% | 3,74% |
| Local 7 kịch bản, split nội phiên | DT d=5 / RF | 95,62% / 98,01% | 96,40% / 98,18% macro | — |

Tỷ lệ chính tái lập khớp `docs/BAO_CAO_CHI_TIET_DU_AN.md:60–97`. Latency trong báo cáo là thời gian của một lời gọi predict theo lô chia cho số mẫu, xem `models/training/ml_utils.py:111–115`. Một lượt gọi API CIC trên PC đo khoảng 10–50 ms tùy model và trạng thái lượt chạy. Các con số này đo hai đại lượng khác nhau. Chỉ dùng log đo riêng của Pi để báo cáo latency edge.

### Split độc lập theo đợt thu

Tôi huấn luyện lại từng model với cấu hình artifact, làm sạch riêng batch Train, rồi đánh giá trên toàn bộ cửa sổ đã trích của batch Test. Đây là stress test hai chiều với hai batch sẵn có. Các board vật lý vẫn xuất hiện ở cả hai phía và các cửa sổ rỗng ngoài TH4 vẫn đã bị lọc từ extractor.

| Train → Test | Số cửa sổ Train/Test | IF Accuracy / F1 | RF Binary Accuracy / F1 | RF Scenario Accuracy / Macro-F1 |
|---|---:|---:|---:|---:|
| batch_01 → batch_02 | 780 / 868 | 97,12% / 97,84% | 98,50% / 98,86% | 98,04% / 97,91% |
| batch_02 → batch_01 | 858 / 799 | 96,12% / 95,79% | 97,62% / 97,41% | 97,50% / 97,44% |

IF sinh lần lượt 16/292 và 24/439 false positive trên cửa sổ normal. RF Scenario có 82/96 burst đúng ở chiều đầu và 57/60 ở chiều ngược. Kết quả hai batch vẫn khả quan. Hai đợt chưa đủ cho ba tập Train/Val/Test độc lập theo batch. Cần thêm đợt mới, hoán đổi vai thiết bị và giữ riêng ít nhất một đợt nghiệm thu sau khi đóng băng model.

### Kiểm tra bổ sung khi giữ riêng cả đợt thu và thiết bị

Cả sáu kịch bản bất thường của `batch_01` được thu trên `esp32_06` và của `batch_02` trên `esp32_05`. Mỗi lượt chỉ chấm trên board chạy bất thường của batch Test, gồm cả 120 cửa sổ normal của board đó. Loại toàn bộ dữ liệu của board Test khỏi batch Train. Giữ nguyên 14 đặc trưng, làm sạch Train theo hàm hiện có và clone cấu hình ba artifact Local để fit lại trong bộ nhớ. IF chỉ fit trên normal Train.

| Train → Test | Board Test | Cửa sổ Train / Test | IF F1 | RF Binary F1 | RF Scenario Macro-F1 |
|---|---|---:|---:|---:|---:|
| batch_01 → batch_02 | esp32_05 | 666 / 696 | 96,03% | 99,39% | 97,91% |
| batch_02 → batch_01 | esp32_06 | 739 / 480 | 89,74% | 99,86% | 99,46% |

Trên cửa sổ có gói, IF đạt F1 95,51% và 95,60%. Độ chênh khi chấm cả cửa sổ rỗng cho thấy cần báo cáo riêng các cửa sổ có gói và kiểm watchdog theo chuỗi thời gian. IF và RF Binary đều có 0/120 false positive ở mỗi lượt trên chính board Test. Mẫu normal này chỉ bao phủ hai board trong hai batch sẵn có. Kết quả bổ sung chưa thay thế đợt nghiệm thu độc lập hoặc xử lý việc trùng phiên trong benchmark Local chính thức.

#### Vì sao Isolation Forest giảm F1 khi tính cả cửa sổ rỗng

| Cửa sổ bất thường được IF phát hiện | Test batch_02 / esp32_05 | Test batch_01 / esp32_06 |
|---|---:|---:|
| TH4 có gói | 0/32 | 0/20 |
| TH4 rỗng | 64/64 | 0/40 |
| TH5 burst | 84/96 | 53/60 |
| Bốn kịch bản bất thường còn lại cộng lại | 384/384 | 240/240 |

Mọi cửa sổ rỗng có cùng vector đầu vào. Hai lần fit cho điểm `decision_function` của vector này lần lượt là −0,013485 và +0,024794. Khi điểm đổi dấu quanh ngưỡng 0, dự đoán thay đổi cho cả nhóm cửa sổ rỗng. Cả hai lượt bỏ sót toàn bộ cửa sổ TH4 còn lưu lượng. Phần nghiệm thu TH4 cần đo từ lúc telemetry ngừng đến khi watchdog báo động và kiểm tra trường hợp kết nối MQTT vẫn giữ keepalive. Hai manifest có 7 phiên mỗi đợt. Muốn Train, Validation và Test độc lập theo đợt và mỗi tập có đủ 7 kịch bản thì cần ít nhất một đợt thu bổ sung đủ 7 kịch bản.

Lệnh kiểm chứng chạy từ thư mục gốc. Model được fit trong bộ nhớ.

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
@'
from pathlib import Path
import joblib
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import accuracy_score, f1_score
from models.training.train_local import _dedup_local_preserve_empty
from pipeline.window_features import FEATURE_COLUMNS_14 as cols
data = pd.read_csv('data/processed/local_feature_windows.csv')
models = [('iso_forest','binary_label'),('rf_binary','binary_label'),('rf_scenario','scenario_label')]
folds = [('batch_01','batch_02','esp32_05'),('batch_02','batch_01','esp32_06')]
for source, target, board in folds:
    train,_ = _dedup_local_preserve_empty(data[(data.batch==source) & (data.device_key!=board)],cols)
    test = data[(data.batch==target) & (data.device_key==board)]
    assert set(train.device_key).isdisjoint(test.device_key)
    print(source, target, board, 'train',len(train), 'test',len(test),'test counts',test.binary_label.value_counts().to_dict())
    for name, label in models:
        model = clone(joblib.load(Path('models/artifacts') / f'local_{name}.joblib'))
        fit_set = train[train.binary_label==0] if name=='iso_forest' else train
        x_fit = fit_set[cols].to_numpy()
        if name=='iso_forest':
            model.fit(x_fit)
        else:
            model.fit(x_fit,fit_set[label])
        if name == 'iso_forest':
            detected = (model.predict(test[cols].to_numpy()) == -1).astype(int)
            audited = test.assign(detected=detected)
            print(audited.groupby(['scenario_label','is_empty_window']).detected.agg(['sum','count']).to_string())
            empty = audited[audited.is_empty_window.eq(1)]
            print('EMPTY DECISION SCORES', sorted(set(model.decision_function(empty[cols].to_numpy()))))
        for mode, evaluated in [('all',test),('nonempty',test[test.is_empty_window==0])]:
            truth=evaluated[label]
            pred=model.predict(evaluated[cols].to_numpy())
            if name=='iso_forest':
                pred=(pred==-1).astype(int)
            average='binary' if label=='binary_label' else 'macro'
            extra=f'FP={((truth==0)&(pred==1)).sum()}' if label=='binary_label' else ''
            print(name,mode,len(evaluated),f'{accuracy_score(truth,pred):.4%}',f'{f1_score(truth,pred,average=average):.4%}',extra)
'@ | python -
```

### Preprocessing và feature engineering

- **Fit chỉ trên Train**. CIC `train_ciciot.py:60–79,91–162`; Local `train_local.py:149–179,194–256`. Các RF/DT dùng `QuantileClipper` + `RobustScaler`; IF của cả hai nguồn chỉ scaler + model, fit trên normal Train. Không có encoder học tham số ở hai luồng này. Quy đổi nhãn dùng hàm/map tĩnh. Clean xử lý NaN/Inf bằng hằng số và dedup toàn tập trước chia; hash kiểm tra exact duplicate, không kiểm phụ thuộc theo nguồn capture. CIC dedup theo X + label, nên hai vector X giống nhau nhưng nhãn xung đột vẫn có thể còn nếu dữ liệu mới xuất hiện trường hợp đó. Local dedup toàn tập theo X (trừ empty), có thể làm mất nhãn xung đột hoặc thay đổi phân bố từng phiên. Cần báo cáo nhóm xung đột và kiểm các cặp split.
- **Lý do IF không dùng QuantileClipper**. Các artifact IF thực tế chỉ có `scaler, clf` và mã `train_local.py:229–236`, `train_ciciot.py:145–152` dùng đúng cách. Clipper học trên Normal sẽ ép nhiều giá trị cực đoan khác nhau về cùng ngưỡng biên. Điều này giữ được yêu cầu tránh cắt spike ở đầu vào IF, còn tác động lên hiệu năng cần kiểm thực nghiệm theo từng nhóm bất thường. Hiện `contamination` cố định 0,05 và không thấy phiên bản hóa quy trình chọn threshold từ Validation.
- **Công thức** `pipeline/window_features.py:40–94` dùng chung. `packet_count=N`, `byte_count=sum(frame.len)`, rate chia 5 giây, len dùng mean/std quần thể/max, IAT dùng hiệu timestamp đã sắp xếp theo ms. Một gói dùng IAT mean/max 5.000 ms và std 0. SYN chỉ tính SYN mở kết nối, bỏ SYN-ACK. FIN/RST là số gói mang cờ. Cửa sổ rỗng có 13 trường bằng 0 và cờ rỗng bằng 1. Test một gói 60 B cho 0,2 pkt/s và 12 B/s. Chuyển 152 gói từ cửa sổ PCAP sang fixture dòng Tshark rồi chạy `_handle_line` cho 14 giá trị giống nhau. Đây là kiểm thử tính toán và parser ở cùng đầu vào, Tshark thật chưa được đối chiếu.
- **Phân bố rỗng** `pipeline/extract_features.py:196–218` giữ 104/156 cửa sổ rỗng của TH4 và loại 109 cửa sổ TH0 rỗng. 52 cửa sổ TH4 còn có gói, nhất quán với việc im telemetry nhưng vẫn có lưu lượng dây. Mã suy luận live bỏ IF khi không có gói, trong khi benchmark IF offline chạy cả vector rỗng. Trình bày riêng IF trên non-empty, watchdog theo sự kiện/mốc heartbeat và hệ thống hybrid theo phiên, giữ bộ trường hợp normal mất Wi-Fi/nguồn nếu nhãn nguyên nhân đã xác minh.

### Khi nào Rule kích hoạt

| Nguồn | Điều kiện hiện tại | Nguồn lưu/hiển thị |
|---|---|---|
| Watchdog | Thiết bị từng gửi, cửa sổ không có gói, hơn 8 giây từ telemetry/heartbeat cuối, trước đó trạng thái online để tạo alert một lần. Chu kỳ kiểm tra 5 giây khiến 8 giây chỉ là ngưỡng. Wire keepalive có thể chặn điều kiện dù telemetry đã ngừng | DB `rule`, model_version `WatchdogRule_v1`. UI gọi Watchdog |
| Hybrid network threshold | RST hoặc SYN hoặc FIN ≥3/5s, hoặc ≥8 pkt/s, hoặc len_mean ≥700 B. Tạo alert nếu IF đánh dấu hoặc ngưỡng trúng. Chọn tên heuristic dùng ngưỡng khác, ví dụ RST ≥2 gọi TH6 và SYN/FIN ≥2 gọi TH3 | DB `ml` khi IF trúng, nếu chỉ ngưỡng thì `rule`; UI hiện gắn mọi `rule` ngoài Tshark thành Watchdog |
| Tshark CONNECT | Tối thiểu 2 MQTT CONNECT trong 15 giây của một device, cooldown 20 giây | DB `tshark`; UI Tshark |
| Tshark CONNACK | Bất kỳ mã CONNACK khác 0 hiện được gọi AUTH_FAILURE, cooldown 10 giây | DB `tshark`; UI Tshark. Fixture mã 3 vẫn trả AUTH_FAILURE dù mã 0x03 biểu thị broker không khả dụng trong MQTT 3.1.1 |

Bằng chứng `pipeline/feature_extractor.py:240–262,289–345`, `pipeline/tshark_collector.py:100–106,201–243`, `backend/static/index.html:233–237`. Fixture thời điểm cuối cách 9 giây cho 0 SILENCE_TIMEOUT khi có một gói dây, hai lần xử lý không có gói sau đó tổng cộng đúng 1 SILENCE_TIMEOUT. Thử collector với kết nối lặp và CONNACK giả lập xác nhận hai sự kiện mang nguồn `tshark`.

## 3. Backend, pipeline, firmware và triển khai

### Nhật ký kiểm thử

| Lệnh hoặc phép thử đã chạy | Kết quả |
|---|---|
| PowerShell lấy danh sách Python rồi truyền tuyệt đối vào `python -m py_compile` | 13/13 tệp Python qua, bao gồm DB và simulator. Đây là kiểm cú pháp |
| `python pipeline/extract_features.py`, `python models/training/train_local.py`, `python models/training/train_ciciot.py` | Qua trên bản sao. Dữ liệu, số dòng, metric ở mục 2 |
| Node 24 `--check` trên JS inline tách từ HTML | Qua. Harness Node VM chạy phương thức Vue thật với fetch/Chart mô phỏng để xác minh xử lý offline, HTTP 503 và màu thẻ |
| Parser PowerShell `ParseFile` cho `scripts/deploy_to_pi5.ps1` | 0 lỗi cú pháp |
| Git Bash `bash -n` cho ba shell script và `wsl --list --quiet` | Git Bash bị Windows chặn khi khởi tạo đối tượng MSYS. WSL chưa cài. Đọc tĩnh ba script |
| PlatformIO `pio run --project-dir .\_audit_scratch_20261119\firmware -j 4` | Cache gốc bị chặn ghi lock. Sau khi đưa platform, toolchain và build dir sang thư mục tạm, cả hai cấu hình bắt đầu build nhưng dừng khi gọi compiler. Chạy `xtensa-esp32s3-elf-g++.exe --version` trên bản gốc và bản sao có cùng SHA-256 đều báo `Illegal System DLL Relocation`. Chưa xác minh biên dịch hoặc flash |
| Mosquitto loopback + Paho, Uvicorn loopback | Mosquitto 2.1.2 mở listener `127.0.0.1:61762` bằng `mosquitto -c .\_audit_scratch_20261119\audit_mosq.conf -v`. Paho gọi `client.connect('127.0.0.1', 61762, 10)` và bị chặn với `WinError 10013` trước khi nhận CONNACK. Phép thử HTTP ở đợt đầu dùng ASGI in-process. Chưa xác nhận luồng MQTT đầu cuối |
| Chrome headless trên bản sao HTML | Mã thoát 2147483651, không có DOM. Kết quả UI dưới đây đến từ HTML/JS, kiểm cú pháp và thực thi phương thức qua Node. Layout, CDN và heap của trình duyệt chưa đo |
| SQLite `PRAGMA integrity_check`, lock injection `BEGIN EXCLUSIVE` trên DB sao chép | DB `ok`, journal `delete`. Mock connection timeout 0,1 s trả HTTP 500 khi read bị khóa. Connection chạy thật đặt timeout 10 s |

Lệnh PowerShell tái lập phần compile, dùng thư mục tạm cho bytecode:

```powershell
$env:PYTHONPYCACHEPREFIX = Join-Path $env:TEMP 'aiot-audit-pyc'
$files = Get-ChildItem backend,pipeline,models,scripts,simulator -Recurse -Filter *.py
python -m py_compile $files.FullName
```

Ba lệnh training/extract có đường dẫn ghi mặc định trong dự án. Chạy trên một bản sao nếu mục tiêu là đối chiếu artifact.

### Toàn bộ API ứng dụng

HTTP kiểm qua FastAPI/Starlette thật với HTTPX ASGITransport. Harness thay thread offload bằng gọi đồng bộ và bỏ phần loopback của event loop. Phép thử xác minh routing, validation, response và logic. Socket, middleware reverse proxy và hiệu năng HTTP thực tế trên Pi là các phép đo riêng.

| Route GET | Dòng trong `backend/app/main.py` | Kết quả / lưu ý |
|---|---:|---|
| `/` | 551–556 | 200, trả HTML 98.308 B. Thiếu HTML sẽ trả JSON 200 |
| `/api/ciciot/info` | 94–98 | 200 với metadata, 404 khi key vắng |
| `/api/devices` | 298–314 | 200, 6 thiết bị seed. Nếu DB lỗi thì không có xử lý trả 503 |
| `/api/alerts`, `/api/windows`, `/api/packets` | 334–379 | 200 với danh sách rỗng ở snapshot. `/api/windows` nhận `limit=-1,0,100000` và trả 200. Khi giữ exclusive lock, `/api/windows` trả 500 |
| `/api/captures`, `/api/captures/download/{filename}` | 381–404 | Danh sách 200 rỗng. File thiếu 404. Khi đặt PCAP fixture vào thư mục phục vụ, tải 200 và nội dung khớp từng byte |
| `/api/system/status` | 406–414 | 200. MQTT luôn ghi Running kể cả khi publish mock báo broker down. Không có health riêng của collector |
| `/api/local/report` | 416–435 | 200 với JSON chuẩn, 500 khi JSON lỗi cú pháp. JSON thiếu ra null, schema mặc định có thể bị hiểu là đã sẵn sàng |
| `/api/logs/windows` | 437–449 | 200, DB snapshot có 0 log runtime. Query chưa giới hạn miền `limit` |
| `/api/logs/files`, `/api/logs/files/{filename}` | 452–474 | 200, liệt kê đúng ba log và trả extract_features.log 6.191 B. Trường `path` cố định đường dẫn Pi nên sai trên Windows |
| `/api/windows/export-csv` | 476–523 | 200, header có đủ 14 đặc trưng và metadata. Tương thích v1 tự điền 0 cho trường chưa đo |
| `/api/local/dataset/preview`, `/api/local/dataset/csv` | 525–543 | 200, tải CSV 199.260 B. Preview đọc CSV toàn bộ mỗi request; CSV hỏng có thể trả 500 |

| Route POST | Dòng | Kết quả / lưu ý |
|---|---:|---|
| `/api/ciciot/replay` | 103–167 | Ba model hợp lệ trả 200. model_type sai trả 200 với UNKNOWN; label sai trả 200 với nhãn ngẫu nhiên. Thiếu tất cả artifact trong fixture trả 404. Cache còn samples nhưng thiếu metadata có thể KeyError, samples rỗng gọi random.choice có thể lỗi. Thiếu riêng model có thể trả UNKNOWN |
| `/api/simulator/trigger` | 169–293 | TH0–TH6 trả 200, TH7 trả 400. Khi thiếu model trả 200 với dự đoán mặc định và score +0,1; file Local IF hỏng trả 500. Chưa có latency, ID phiên chạy hay trạng thái đánh giá đúng/sai |
| `/api/devices/{device_id}/control` | 316–332 | Device lạ và scenario sai vẫn gọi publish và trả success 200 trong fixture. Broker lỗi trả status:error với HTTP 200. Publish thành công xác nhận thao tác gửi từ gateway, chưa xác nhận node đã nhận hay áp dụng |

Các Pydantic model kiểm trường bắt buộc và kiểu, thiếu enum/danh sách hợp lệ ở một số đường vào. Các endpoint thiếu xử lý lỗi cần bắt lỗi dự kiến theo lớp như artifact/schema/DB/MQTT, chuyển thành mã 4xx/503 có log nội bộ. Riêng SQLite dùng mỗi hàm một connection nên `check_same_thread=False` không tự cung cấp serialization, còn writer từ MQTT callback, cửa sổ, Tshark và control có thể tranh nhau. Tshark xóa batch pending trước commit, vì thế nếu ghi thất bại, batch mất khỏi hàng đợi. `windows` được ghi cho cả sáu thiết bị mỗi vòng và không có retention, theo nhịp lý tưởng xấp xỉ 103.680 dòng/ngày. Tham chiếu `backend/app/db/database.py:8–12,35–63`, `pipeline/feature_extractor.py:117–137,183–238,378–399`, `pipeline/tshark_collector.py:273–319`.

### Firmware và simulator

| Kịch bản | Firmware `firmware/src/main.cpp` | Điều quan sát được khi audit |
|---|---|---|
| TH0 | Publish JSON khoảng 2 s, dòng 275–280 | Đúng topic telemetry. Nhiệt độ/độ ẩm do firmware sinh ngẫu nhiên tại 180–195 |
| TH1 | Publish mỗi 65 ms, 283–287 | Đây là tốc độ gửi MQTT dự kiến khoảng 15,38 msg/s. Wire pkt/s bao gồm cả ACK và phụ thuộc mạng |
| TH2 | Publish payload có padding mỗi 2 s, 186–197,249,290–295 | Payload buffer 1.800 B, MQTT buffer yêu cầu 2.048 B. Cả `setBufferSize` và `publish` không kiểm kết quả. Một MQTT message có thể sinh nhiều frame TCP |
| TH3 | Publish rồi ngắt MQTT mỗi 3 s, 298–305 | Có đường reconnect và subscribe lại tại 149–174. Kết nối lại cũng phát heartbeat và thêm lưu lượng giao thức |
| TH4 | Bỏ publish, vẫn `client.loop()`, 252–260,307–308 | Dừng telemetry, giữ MQTT session. Đây là nguyên nhân cần đo Watchdog theo tuổi telemetry riêng với cờ empty |
| TH5 | 20 publish cách 50 ms, nghỉ 5 s, 310–321 | Có burst trên firmware. Biến đếm không reset khi bắt đầu kịch bản mới, nên lặp thử theo lệnh có thể bắt đầu dở đợt |
| TH6 | Cố ý dùng thông tin xác thực thử sai, nhánh 149–174,324–330 | Khi broker từ chối liên tiếp, vòng reconnect chặn MQTT callback/nút BOOT, có thể cần reset vật lý. Capture thật có lưu lượng bắt tay, nhưng nguồn xác nhận nguyên nhân cần log broker hoặc CONNACK được giải mã đúng theo phiên |

Firmware và simulator khớp mẫu topic `wievac/<device>/telemetry`, `wievac/control/<device>`, `wievac/<device>/heartbeat`, xem `main.cpp:233–249` và `simulator/virtual_nodes.py:27–37`. Simulator độc lập cần broker. Test trực tiếp callback xác nhận TH0/1/2/4 có handler, TH3/5/6 không đổi cấu hình; trên node mặc định reconnect, đổi sang TH0 vẫn giữ cờ reconnect. Cấu hình TH5 có `burst=True` nhưng vòng gửi không đọc cờ này. Khi disconnect chủ động, code gọi `connect` lại mà không dựng lại luồng/subscribe trong `on_connect`. Các node ảo dùng chung ID payload/topic với board thật, nên pipeline và dashboard có thể ghi nhận nguồn ảo là Hardware. Có bản Arduino khác ở `firmware/esp32_telemetry/esp32_telemetry.ino` bên cạnh file build PlatformIO. Nên chỉ định rõ firmware chuẩn khi flash và ghi build ID vào metadata capture.

### Deployment và khôi phục

- Windows lấy root theo vị trí script, collect_sessions lấy thư mục phiên tương đối với dự án. Mặc định Windows→Pi khớp `/home/pi/AIoT` nếu dùng user pi. Nếu đổi `-RemoteDir` hoặc `-PiUser`, systemd và `start_gateway.sh` vẫn dùng giá trị cứng. Deploy chỉ mang code, artifact, CSV processed và log, không mang CSV CIC gốc, phiên capture, simulator hay test. Root custom chưa đi xuyên suốt. Bằng chứng `scripts/deploy_to_pi5.ps1:1–9,19–31,39–49`, `scripts/install_systemd_pi5.sh:10–19,31–40`, `scripts/start_gateway.sh:3–15`.
- `scripts/setup_pi5.sh:12–34` cài dependency không có lock, với Python global. `firmware/platformio.ini:1–7,12–23` chưa khóa phiên bản platform. Cần pin cùng môi trường train/inference, version model/schema và kiểm artifact trước khi đổi bản triển khai. Thiếu checksum và cập nhật nguyên tử cho gói model khiến report với model chạy có thể lệch phiên bản.
- `scripts/collect_sessions.py:57–66,123–146,160–222` có thể ghi đè capture nếu dùng lại batch. Việc dừng pipeline và dò node diễn ra trước `try/finally`, vì vậy nếu lỗi ngay bước kết nối MQTT thì restart trong finally không chạy. Thay đổi cấu hình/restart broker trong TH6 tác động cả client khác và cleanup khôi phục theo mẫu cứng, không giữ nguyên cấu hình trước khi thu. Nên giữ trạng thái trước khi chạy, ghi manifest từng phiên theo cơ chế nguyên tử và đưa thao tác thay đổi dịch vụ vào một khối cleanup có xác minh.
- Capture Live dùng `wlan0` cứng, collect có `--interface`. `scripts/setup_pi5.sh:17–18` cấp nhóm wireshark cho user đang chạy script, trong khi service chạy user pi. Kiểm tra đúng NIC, quyền `dumpcap` của service account, báo cáo lỗi và trạng thái capture đến UI.
- Nếu MQTT từ chối kết nối ở startup, `pipeline/feature_extractor.py:392–415` log rồi tiếp tục tiến trình ngoài, vòng feature chưa chạy. Fixture xác nhận `running=False` và `loop_start=0`. Systemd có thể vẫn nhìn thấy tiến trình hoạt động nên `Restart=always` chưa cứu tình huống này. Dùng retry có trạng thái hoặc thoát lỗi để service manager restart.
- `scripts/setup_pi5.sh:20–24`, `backend/app/main.py:27–33,319–332` và `scripts/install_systemd_pi5.sh:32–36` cho thấy broker mặc định ẩn danh trên mọi interface, API bind rộng và control không có lớp phân quyền trong mã. Cấu hình SSID/thông tin kết nối nằm cứng ở `firmware/src/main.cpp:17–25`. Cần tách cấu hình, giới hạn mạng lab, dùng tài khoản/ACL cho topic, khóa API control và hạn chế quyền đọc file capture/log. Dữ liệu capture là raw frame, cần quản lý như dữ liệu có thể chứa MQTT payload hoặc thông tin nhạy cảm.

## 4. Frontend và UX

| Mục | Kết quả |
|---|---|
| Live charts | `index.html:1250–1277,1485–1508` poll 3 s. Backend chạy sleep 5 s rồi xử lý, nên khoảng cách giữa các cửa sổ có thể dài hơn 5 s. Chart grouped theo `created_at`, giới hạn 10 điểm, chart cũ `destroy()` trước khi dựng lại. Chưa thấy mảng lịch sử tăng vô hạn. Poll chồng khi request chậm và interval không được hủy khi unmount. Chart cũng tự điền 0 cho node thiếu dữ liệu trong bucket. Cần phân biệt 0 quan sát được, bucket thiếu và dữ liệu cũ |
| Live controls | Nút hiện TH0–TH5 theo thứ tự UI, TH6 chỉ có trong Demo Lab và luồng thu phiên. `index.html:1390–1398` bỏ qua body HTTP, trạng thái lỗi và ACK. Thẻ node có thể đổi màu vì kịch bản đã đặt trước khi có alert thật |
| Dữ liệu 5s | `index.html:284–321` hiển thị count/byte/rate, len_mean, iat_mean và ba cờ TCP, thiếu len_std, len_max, iat_std, iat_max, is_empty_window trong bảng. CSV export có đủ 14. Link capture đúng endpoint và thử tải fixture thành công; 14 tệp phiên thu thực nằm ở thư mục khác với kho capture Live. Log file có link tải và log runtime có bảng |
| Demo Lab | Ground truth và dự đoán có chỗ riêng. CIC hiển thị latency và chọn RF Multi/RF Binary/IF. Local có thanh score và hiển thị RF Scenario, thiếu latency và lịch sử. Nhãn CIC chủ yếu từ metadata, có danh sách fallback hardcode khi API chưa sẵn sàng tại `1205–1209` |
| Mô hình & Huấn luyện | Bảng baseline đọc metadata/report và các metric chính khớp báo cáo trên artifact được kiểm. Hiện thấy hai ma trận nhị phân, CIC RF và Local IF, cùng tóm tắt ô của Local RF Binary. CIC RF Multi có ma trận trong JSON nhưng UI không dựng ma trận 34×34. Local RF Scenario thiếu ma trận 7×7 và F1 từng lớp, UI có accuracy theo kịch bản. KPI CIC dùng mặc định 97,72%, 95,84%, 22,83%, 16,81% khi thiếu dữ liệu ở `637–643`; biểu đồ fallback về 0 tại `1519–1536`. Nên có một trạng thái chưa có benchmark và hiển thị timestamp, data hash, model hash |
| Backend mất kết nối | Node VM tái hiện kết nối mất vẫn giữ node online cũ. Khi GET devices trả JSON lỗi HTTP 503, client gán object vào `devicesList`, sau đó `.filter()` lỗi TypeError. Local sim lưu `{detail: ...}` như kết quả và nhánh template có thể hiện Bình thường. Xem `index.html:1187–1192,1324–1423,563–568` |
| Mạng không Internet | Tailwind, Vue, Chart được tải từ CDN tại `index.html:8–10`; logic gọi `Vue` ở 1137, `Chart` ở 1251. Khi thiếu script, app có thể không mount hoặc không khởi động polling. Triển khai nội mạng nên tự phục vụ bản đã pin. Chưa kiểm được layout/hiệu năng trên Chrome/Pi do giới hạn nêu ở mục 3 |

## 5. Danh sách lỗi và kế hoạch sửa

| ID / Mức | Lỗi và tác động | Bằng chứng |
|---|---|---|
| C01 · CRITICAL | Live tô viền cảnh báo theo scenario. Vi phạm trực tiếp điều 11, 12.4 và 16.1 của bản bổ sung. Node VM tạo TH1 với 1 pkt/s, 60 B/s, 0 alert vẫn ra true | `backend/static/index.html:157,1311–1315` |
| C02 · CRITICAL | Demo Local gắn score -0,35 và nhãn anomaly cho vector rỗng dưới tên IF mà không gọi IF. Cùng artifact, predict trực tiếp cho -1 với score **-0,0651**. Khi thiếu artifact, endpoint lại trả normal/+0,1. Đây là kết quả được gắn tên model sai nguồn, dù ground truth nằm cột riêng | `backend/app/main.py:208–235,259–292`; `backend/static/index.html:559–585` |
| C03 · CRITICAL | Đánh giá Local gọi Test độc lập trong khi shared 14/14 phiên, vi phạm mục 12.2. Train/Val và Val/Test còn có hai time bin chung mỗi cặp do cắt theo hàng khi nhiều node cùng timestamp. Báo cáo cũ ghi overlap 0 mà không phân biệt hash và session | `models/training/train_local.py:34–80,142–184`; `docs/BAO_CAO_CHI_TIET_DU_AN.md:75–81` |
| M01 · MAJOR | Watchdog bỏ sót kịch bản ngừng telemetry nếu wire có keepalive. Benchmark `Rule + Watchdog` chỉ dùng cờ empty theo từng row; chưa kiểm logic timeout và false alerts của Watchdog thật | `pipeline/feature_extractor.py:240–262`; `models/training/ml_utils.py:34–62`; `models/training/train_local.py:194–199` |
| M02 · MAJOR | Shared feature function nhưng offline/live có đầu vào khác. Live chia theo lúc drain buffer, không xếp frame theo epoch timestamp vào cửa sổ, có giới hạn 5.000 gói/device. Fallback dùng kích thước MQTT + 40 B, timestamp on_message và ba cờ TCP false, rồi vẫn đưa vào model train trên wire. Parser offline chỉ nhận một số link type và IPv4/TCP, batch IP map có thể bị cập nhật qua nhiều phiên | `pipeline/feature_extractor.py:97–112,176–221,381–389`; `pipeline/tshark_collector.py:235–266`; `pipeline/window_features.py:132–194`; `pipeline/extract_features.py:124–126,178–217` |
| M03 · MAJOR | Collector preload sai tên cột. DB dùng `id` nhưng query `device_key`; exception bị nuốt. Sau restart, thiết bị đã biết IP có map rỗng cho đến khi gặp metadata nhận diện. Fixture với IP seed tái hiện map rỗng | `pipeline/tshark_collector.py:56–66`; `backend/app/db/database.py:18–33` |
| M04 · MAJOR | Nguồn / nguyên nhân cảnh báo bị gộp. RST heuristic gán TH6, còn CONNACK nào khác 0 cũng gán Auth Failure. `predicted_label` có thể chứa tên heuristic ngay khi source là ML, và UI mặc định gọi alert type rule là Watchdog. Dữ liệu thiếu cột DB độc lập cho rule, IF, RF và ground truth | `pipeline/feature_extractor.py:291–345`; `pipeline/tshark_collector.py:201–233`; `backend/static/index.html:233–237` |
| M05 · MAJOR | Contract replay/simulator lỏng. Replay nhãn sai trả mẫu khác, model sai trả UNKNOWN 200. Artifact hỏng ra 500, và một joblib CIC nạp lỗi chặn load các thành phần sau trong cùng khối. API không lưu lịch sử, chỉ lấy một mẫu ngẫu nhiên | `backend/app/main.py:46–85,103–166,208–215,416–435` |
| M06 · MAJOR | UI khi API lỗi có thể hiển thị cũ hoặc vỡ render, khó phân biệt mất kết nối với thiết bị im lặng. CDN tạo phụ thuộc Internet cho dashboard nội mạng | `backend/static/index.html:8–10,1137,1188–1192,1250–1277,1324–1423` |
| M07 · MAJOR | Health MQTT là chuỗi cố định, control không validate thiết bị/kịch bản và UI bỏ qua kết quả. Network/MQTT failure chưa được báo đúng. Pipeline startup thất bại có thể tồn tại ở trạng thái nửa khởi động | `backend/app/main.py:316–332,406–414`; `backend/static/index.html:1390–1398`; `pipeline/feature_extractor.py:392–415` |
| M08 · MAJOR | SQLite trả 500 khi bị khóa, thời gian chờ 10 s có thể làm backlog. Batch packet/alert đã lấy khỏi buffer trước transaction có thể mất khi DB lỗi. Thiếu retention windows/alerts và index theo luồng truy vấn thời gian/thiết bị | `backend/app/db/database.py:8–12,35–103`; `pipeline/tshark_collector.py:273–319`; `backend/app/main.py:334–379` |
| M09 · MAJOR | Virtual nodes đồng nhất định danh với board thật, thiếu TH3/5/6 ở handler, cờ burst không dùng và reconnect của node TH3 còn sót khi đổi về TH0. TH6 firmware có thể tự khóa kênh điều khiển. Cần phân biệt nguồn và tách bằng chứng broker | `simulator/virtual_nodes.py:1–5,16–22,27–99`; `firmware/src/main.cpp:149–175,252–269,324–330` |
| M10 · MAJOR | Quyền API/MQTT và bí mật cấu hình chưa đáp ứng rubric. Deploy và setup mặc định thiếu khóa version, service path cứng. Collect có điểm lỗi xảy ra trước cleanup và thao tác trên cấu hình broker đang dùng | `backend/app/main.py:27–33,319–332`; `firmware/src/main.cpp:17–25`; `scripts/setup_pi5.sh:17–34`; `scripts/collect_sessions.py:88–96,132–160,213–222`; `scripts/install_systemd_pi5.sh:10–40` |
| M11 · MAJOR | Khi thiếu/hỏng model live, code huấn luyện baseline tổng hợp rồi lưu đè cùng đường dẫn artifact chuẩn và tiếp tục suy luận với schema v1. Thông tin model version ở alert chưa nhận diện đúng binary/version được triển khai | `pipeline/feature_extractor.py:50–86,331–345` |
| M12 · MAJOR | Bốn tab có điều hướng nhưng thiếu hành trình nghiên cứu/dữ liệu và đối chiếu theo phiên; KPI benchmark có hằng số khi thiếu artifact. Phạm vi phần cứng và UI lệch 4/6 node | `backend/static/index.html:57–67,284–321,603–643,1168–1175,1250–1277`; `backend/app/main.py:525–543`; `backend/app/db/database.py:105–119` |
| M13 · MAJOR | Nhãn Local lấy từ tên manifest/cửa sổ theo lịch, thiếu ACK/thời điểm xác nhận có hiệu lực theo node. Metadata CIC chưa ghi nguồn capture hoặc recipe tạo subset. Chưa chứng minh các lớp có khó khăn tương đương hay Test CIC độc lập theo capture | `pipeline/extract_features.py:178–229`; `scripts/collect_sessions.py:161–204`; `models/training/train_ciciot.py:43–70,248–269` |
| m01 · MINOR | Response logs.path luôn nói `/home/pi/AIoT/logs/...`, kể cả chạy trên PC. TH1/TH2 simulator mô tả bằng đơn vị packet dù firmware nói MQTT message/payload | `backend/app/main.py:452–463`; `backend/static/index.html:1176–1183`; `firmware/src/main.cpp:283–295` |
| E01 · ENHANCEMENT | Bổ sung `perf_counter`, p50/p95 theo lô và từng cửa sổ, cùng tỷ lệ dropped frame, cửa sổ trả trễ, độ trễ từ ACK kịch bản đến alert và alert/hour. Đo riêng detect delay theo phiên | `models/training/ml_utils.py:111–115`; `backend/app/main.py:128–162`; `pipeline/feature_extractor.py:176–181,358–389` |
| E02 · ENHANCEMENT | Chọn ngưỡng IF trên Validation có mục tiêu FPR, báo cáo balanced accuracy, macro và per-class F1/Recall, confusion matrices, số mẫu và CIs theo phiên/đợt | `models/training/train_local.py:229–236,306–319`; `models/training/train_ciciot.py:145–152,198–212` |

### Thứ tự sửa trước bảo vệ

1. **Đưa UI và API về đúng bằng chứng**. Xóa nhánh màu Live dựa vào scenario, tách cột kịch bản yêu cầu khỏi trạng thái quan sát. Trong Demo, ghi trạng thái model unavailable bằng 503. Với empty, trả rule hoặc trạng thái không suy luận, hoặc chạy IF thật nếu mục đích là chứng minh hành vi IF offline. Chặn trang dùng dữ liệu lỗi như kết quả. Cập nhật lời thuyết trình để score thực và nguồn rule được gọi đúng tên.
2. **Tách phiên, tái train và cập nhật mọi số liệu bên dưới**. Thêm `session_id`, `capture_id`, ACK/actual start/end và build ID vào CSV/manifest. Chia toàn nhóm trước khi fit, đóng băng manifest split, kiểm hash cả ba cặp và audit nhãn xung đột. Thêm ít nhất một batch để có Train/Val/Test riêng; ghi provenance của CIC subset và giữ capture/file group nếu nguồn cho phép. Biểu đồ và demo samples phải đọc cùng phiên bản báo cáo/model.
3. **Chuẩn hóa Live**. Dùng cửa sổ 5 giây theo timestamp frame và một điểm thống nhất để tạo feature. Với nguồn MQTT fallback, hiển thị `degraded` hoặc dùng baseline thật riêng có schema nguồn tương ứng. Sửa preload. Tách rule decision, ML prediction, RF scenario và score trong DB/API. Gắn `window_id` và `capture_id` vào alert. Watchdog ưu tiên tín hiệu ứng dụng. Gom/phân cấp alert lặp và kiểm chứng mã từ broker trước khi gọi lỗi xác thực.
4. **Kiểm thử vòng kín trên Pi**. Bổ sung API health kiểm freshness của pipeline, trạng thái capture, nguồn thiết bị và model version. Test thiếu/corrupt artifact, startup broker down, DB lock, NIC sai, khôi phục dịch vụ, và mạng không Internet. Chạy 30–60 phút normal với lưu lượng thực rồi chạy lặp các kịch bản đã định, đo false alerts/giờ, throughput và latency p50/p95. Với SQLite cùng host, cân nhắc WAL, transaction ngắn, retry bounded và hàng đợi giữ bản ghi tới khi commit. Thử lại tải đồng thời trên Pi trước khi công bố mức ổn định.
5. **Hoàn thiện tab và gói tái lập**. Quản lý phiên Local, xem đủ 14 đặc trưng với nhãn thật/dự đoán, liên kết PCAP và log về đúng phiên. Tách demo replay holdout và software simulation thành chế độ người dùng chọn. CIC Lab thêm phân bố theo lớp, ma trận đa lớp và phiên bản benchmark, cho phép offline training/import theo workflow đã định. Khóa dependency, version và đường dẫn cài đặt. Gói model/report/sample phát hành theo một version và có kiểm tra trước khi service reload.

### Mã sửa mẫu

Mẫu Local endpoint giữ kết quả sẵn có từ model thật và quá trình lựa chọn mẫu được kiểm soát. Đường Live có thể dùng Watchdog riêng theo tuổi telemetry. Đoạn dưới minh họa logic trả kết quả, cần ghép vào schema response của dự án.

```python
from time import perf_counter

from fastapi import HTTPException
import numpy as np

def evaluate_local_window(model, features):
    if model is None:
        raise HTTPException(status_code=503, detail="Local model unavailable")
    if set(features) != set(FEATURE_COLUMNS_14):
        raise HTTPException(status_code=422, detail="Invalid Local feature schema")
    if features["is_empty_window"]:
        return {
            "ml_prediction": None,
            "anomaly_score": None,
            "inference_ms": None,
            "inference_status": "empty_window",
        }

    x = np.array([[features[name] for name in FEATURE_COLUMNS_14]], dtype=float)
    if not np.isfinite(x).all():
        raise HTTPException(status_code=422, detail="Non-finite Local feature")
    started = perf_counter()
    score = float(model.decision_function(x)[0])
    return {
        "ml_prediction": "anomaly" if score < 0 else "normal",
        "anomaly_score": score,
        "inference_ms": (perf_counter() - started) * 1_000,
        "inference_status": "complete",
    }
```

Chỉ tô cảnh báo từ các sự kiện thật do backend trả. UI nên dùng riêng style cho trạng thái kịch bản yêu cầu và trạng thái vận hành.

```javascript
isNodeAnomalous(dev) {
  const now = Date.now() / 1000;
  return this.alertsList.some(alert =>
    alert.device_key === dev.id && now - alert.created_at < 15
  );
}
```

Sửa truy vấn preload và buộc kiểm độc lập trước khi tính metric. `session_id` phải duy nhất giữa các batch.

```sql
SELECT id AS device_key, ip_address
FROM devices
WHERE ip_address IS NOT NULL AND ip_address <> '';
```

```python
from itertools import combinations

def validate_split(splits):
    for (left_name, left), (right_name, right) in combinations(splits.items(), 2):
        overlap = set(left["session_id"]) & set(right["session_id"])
        if overlap:
            raise ValueError(f"{left_name}/{right_name} share {len(overlap)} sessions")
```

### Những câu hỏi Hội đồng có thể đặt

- **“Tại sao nói độc lập nếu cả hai bên cùng phiên?”** Báo rõ metric 98,01% là split nội phiên của bản hiện tại. Trình bày thêm kết quả giữ riêng từng batch và số board trùng. Chứng minh độc lập sau khi thu thêm batch và sửa protocol.
- **“RF đa lớp 22,83% có gọi đúng 33 kiểu không?”** Báo 16,81% macro-F1 cùng ma trận và support theo lớp. Dùng RF Binary cho câu hỏi phát hiện; dùng multiclass để đo khó khăn khi gọi loại. Với RF Binary CIC, 25,33% FPR benign là chi phí đáng kể dù F1 cao, do tỷ lệ dữ liệu Attack lớn.
- **“Sao TH4 và TH6 đều 100%?”** Mỗi kịch bản chỉ có 24 cửa sổ Test trong split nội phiên. TH4 có 104/156 cửa sổ rỗng ở toàn bộ dataset. TH6 gắn nhãn từ phiên, không được đánh đồng với chẩn đoán xác thực từ RST. Công bố kết quả theo phiên và đối chiếu broker/timestamp.
- **“Hệ thống có chạy ổn định trên Pi 5 khi Wi‑Fi nhiễu?”** Snapshot DB gốc có 6 device seed và 0 window/alert/log runtime/packet/experiment. PCAP cho thấy có dữ liệu thu offline, tài liệu vận hành nêu số CPU/RAM nhưng không kèm trace thô trong snapshot này. Cần bổ sung nhật ký runtime có giờ, trạng thái Wi‑Fi/broker, dropped frames, false alerts/giờ và p50/p95 từ Pi.
- **“Khi mất model hoặc mất mạng thì có thể tin vào màn hình không?”** Bản audit tái hiện tình trạng trả kết quả mặc định, health luôn Running, lỗi shape trên UI. Đây là ba trường hợp ưu tiên chạy lại sau khi sửa. Demo đạt khi người xem nhận ra nguồn kết quả, trạng thái cũ và lỗi ngay trên giao diện.

### Tài liệu đối chiếu kỹ thuật

- [scikit-learn — Common pitfalls and data leakage](https://scikit-learn.org/stable/common_pitfalls.html)
- [scikit-learn — Cross-validation cho dữ liệu có nhóm](https://scikit-learn.org/stable/modules/cross_validation.html)
- [SQLite — Write-Ahead Logging](https://www.sqlite.org/wal.html)
- [Eclipse Mosquitto — Authentication methods](https://mosquitto.org/documentation/authentication-methods/)
- [OASIS — MQTT 3.1.1, bảng mã CONNACK](https://docs.oasis-open.org/mqtt/mqtt/v3.1.1/mqtt-v3.1.1.pdf)

