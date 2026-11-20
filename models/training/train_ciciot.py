import json
import os
import sys
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.tree import DecisionTreeClassifier

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from models.training.ml_utils import (
    QuantileClipper,
    RuleThresholdBaseline,
    clean_dataframe,
    eval_binary_metrics,
    measure_inference_latency_ms,
)


def train_ciciot_models(
    data_path=os.path.join(BASE_DIR, "data", "raw", "ciciot2023_subset.csv"),
    output_dir=os.path.join(BASE_DIR, "models", "artifacts"),
):
    logs = []

    def log(msg=""):
        print(msg)
        logs.append(msg)

    os.makedirs(output_dir, exist_ok=True)

    log("======================================================================")
    log("BƯỚC 1: NẠP VÀ LÀM SẠCH DỮ LIỆU CICIoT2023")
    log("======================================================================")
    df_raw = pd.read_csv(data_path)
    feature_cols = [c for c in df_raw.columns if c != "label"]
    df_clean, clean_stats = clean_dataframe(df_raw, feature_cols, dedup_subset=feature_cols + ["label"])
    labels_list = sorted(df_clean["label"].unique().tolist())

    log(f"[DATA] Số lượng bản ghi ban đầu: {clean_stats['raw_rows']:,} dòng x {len(feature_cols)} đặc trưng ({len(labels_list)} lớp).")
    log(f"[DATA] Xử lý giá trị NaN / ±Inf: Đã chuẩn hóa {clean_stats['nan_inf_cells_fixed']} ô lỗi.")
    log(f"[DATA] Lọc trùng lặp trước khi chia tập (Anti-Data Leakage): Đã loại bỏ {clean_stats['duplicates_removed']:,} dòng trùng.")
    log(f"[DATA] Dữ liệu sạch còn lại: {clean_stats['clean_rows']:,} dòng.")

    X = df_clean[feature_cols].copy()
    y_multi = df_clean["label"].copy()
    y_bin = y_multi.apply(lambda v: 0 if v == "BenignTraffic" else 1)

    log("======================================================================")
    log("PHÂN CHIA DỮ LIỆU CHẶT CHẼ (70% TRAIN / 15% VAL / 15% TEST ĐÓNG BĂNG)")
    log("======================================================================")
    X_train, X_temp, y_m_train, y_m_temp, y_b_train, y_b_temp = train_test_split(
        X, y_multi, y_bin, test_size=0.30, random_state=42, stratify=y_multi
    )
    X_val, X_test, y_m_val, y_m_test, y_b_val, y_b_test = train_test_split(
        X_temp, y_m_temp, y_b_temp, test_size=0.50, random_state=42, stratify=y_m_temp
    )

    # Kiểm tra trùng chéo giữa Train và Test (Data Leakage Check)
    train_hashes = set(pd.util.hash_pandas_object(X_train, index=False))
    test_hashes = set(pd.util.hash_pandas_object(X_test, index=False))
    overlap_count = len(train_hashes & test_hashes)

    # Cắt ngoại lệ (1%-99%) CHỈ fit trên Train
    clipper_probe = QuantileClipper(0.01, 0.99).fit(X_train)
    clipper_probe.transform(X_train)
    clipped_train = clipper_probe.last_clipped_cells_
    clipper_probe.transform(X_val)
    clipped_val = clipper_probe.last_clipped_cells_
    clipper_probe.transform(X_test)
    clipped_test = clipper_probe.last_clipped_cells_

    log(f"1. Tập TRAIN (70%):        {len(X_train):,} mẫu (Benign: {(y_b_train==0).sum():,} | Attack: {(y_b_train==1).sum():,})")
    log(f"2. Tập VALIDATION (15%):   {len(X_val):,} mẫu")
    log(f"3. Tập TEST ĐÓNG BĂNG (15%): {len(X_test):,} mẫu")
    log(f"[ANTI-LEAKAGE] Trùng lặp đặc trưng giữa Train và Test: {overlap_count} mẫu (Chuẩn 0 rò rỉ).")
    log(f"[OUTLIER] QuantileClipper (1%-99%) & RobustScaler chỉ FIT trên Train -> Đã clip {clipped_train:,} ô Train, {clipped_val:,} ô Val, {clipped_test:,} ô Test.")

    log("======================================================================")
    log("BƯỚC 2: HUẤN LUYỆN BASELINE ĐỐI CHUẨN (FIT TRÊN TẬP TRAIN)")
    log("======================================================================")

    # Baseline 1: Rule Threshold đơn giản (chỉ dùng ngưỡng Q99 của Benign trên Train)
    key_names = [c for c in ["Rate", "Tot sum", "Header_Length", "flow_duration", "AVG"] if c in feature_cols]
    key_indices = [feature_cols.index(c) for c in key_names]
    t0 = time.time()
    rule_base = RuleThresholdBaseline(key_indices=key_indices, quantile=0.99)
    rule_base.fit(X_train[y_b_train == 0].values)
    t_train_rule = round(time.time() - t0, 3)

    # Baseline 2: Decision Tree nông (Binary)
    t0 = time.time()
    dt_bin_base = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", DecisionTreeClassifier(max_depth=3, random_state=42)),
    ])
    dt_bin_base.fit(X_train.values, y_b_train.values)
    t_train_dt_bin = round(time.time() - t0, 3)

    # Baseline 3: Decision Tree nông (Multiclass 34 lớp)
    t0 = time.time()
    dt_multi_base = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", DecisionTreeClassifier(max_depth=6, random_state=42)),
    ])
    dt_multi_base.fit(X_train.values, y_m_train.values)
    t_train_dt_multi = round(time.time() - t0, 3)

    val_rule_preds, _ = measure_inference_latency_ms(rule_base.predict, X_val.values)
    val_rule_m = eval_binary_metrics(y_b_val.values, val_rule_preds)
    val_dt_preds, _ = measure_inference_latency_ms(dt_bin_base.predict, X_val.values)
    val_dt_m = eval_binary_metrics(y_b_val.values, val_dt_preds)
    val_dt_multi_acc = round(float(accuracy_score(y_m_val.values, dt_multi_base.predict(X_val.values))), 4)

    log(f"-> [Baseline Rule Threshold]    Validation: Acc={val_rule_m['accuracy']*100:.2f}% | Prec={val_rule_m['precision']*100:.2f}% | Rec={val_rule_m['recall']*100:.2f}% | F1={val_rule_m['f1_score']*100:.2f}%")
    log(f"-> [Baseline DecisionTree d=3]  Validation: Acc={val_dt_m['accuracy']*100:.2f}% | Prec={val_dt_m['precision']*100:.2f}% | Rec={val_dt_m['recall']*100:.2f}% | F1={val_dt_m['f1_score']*100:.2f}%")
    log(f"-> [Baseline DecisionTree 34c]  Validation: Acc={val_dt_multi_acc*100:.2f}% (dùng cho bài toán gọi tên 34 lớp)")

    log("======================================================================")
    log("BƯỚC 3: HUẤN LUYỆN CÁC MÔ HÌNH CHÍNH (SCIKIT-LEARN PIPELINE)")
    log("======================================================================")

    # Mô hình 1 (Phát hiện bất thường có giám sát): Random Forest Binary
    t0 = time.time()
    rf_bin_pipe = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", RandomForestClassifier(n_estimators=80, max_depth=16, random_state=42, n_jobs=-1)),
    ])
    # Fit riêng từng bước hoặc gọi fit trên numpy array; bọc nhãn str để tương thích /api/ciciot/replay ('benign'/'attack')
    y_b_train_str = y_b_train.map({0: "benign", 1: "attack"}).values
    rf_bin_pipe.fit(X_train.values, y_b_train_str)
    t_train_rf_bin = round(time.time() - t0, 3)

    # Mô hình 2 (Phát hiện bất thường không giám sát): Isolation Forest (CHỈ fit trên Benign của Train)
    # Không gắn QuantileClipper(Benign) vào Isolation Forest vì sẽ cắt mất gai tấn công về vùng bình thường
    t0 = time.time()
    iso_pipe = Pipeline([
        ("scaler", RobustScaler()),
        ("clf", IsolationForest(n_estimators=100, contamination=0.05, random_state=42, n_jobs=-1)),
    ])
    iso_pipe.fit(X_train[y_b_train == 0].values)
    t_train_iso = round(time.time() - t0, 3)

    # Mô hình 3 (Phân loại sâu 34 lớp): Random Forest Multiclass
    t0 = time.time()
    rf_multi_pipe = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", RandomForestClassifier(n_estimators=80, max_depth=16, random_state=42, n_jobs=-1)),
    ])
    rf_multi_pipe.fit(X_train.values, y_m_train.values)
    t_train_rf_multi = round(time.time() - t0, 3)

    val_rf_bin_raw = rf_bin_pipe.predict(X_val.values)
    val_rf_bin_m = eval_binary_metrics(y_b_val.values, [0 if p == "benign" else 1 for p in val_rf_bin_raw])
    val_iso_raw = iso_pipe.predict(X_val.values)
    val_iso_m = eval_binary_metrics(y_b_val.values, [0 if p == 1 else 1 for p in val_iso_raw])
    val_rf_multi_pred = rf_multi_pipe.predict(X_val.values)
    val_rf_multi_acc = round(float(accuracy_score(y_m_val.values, val_rf_multi_pred)), 4)

    log(f"-> [Random Forest (Binary)]     Validation: Acc={val_rf_bin_m['accuracy']*100:.2f}% | Prec={val_rf_bin_m['precision']*100:.2f}% | Rec={val_rf_bin_m['recall']*100:.2f}% | F1={val_rf_bin_m['f1_score']*100:.2f}%")
    log(f"-> [Isolation Forest (Benign)]  Validation: Acc={val_iso_m['accuracy']*100:.2f}% | Prec={val_iso_m['precision']*100:.2f}% | Rec={val_iso_m['recall']*100:.2f}% | F1={val_iso_m['f1_score']*100:.2f}%")
    log(f"-> [Random Forest (34 lớp)]     Validation: Acc={val_rf_multi_acc*100:.2f}% (Macro F1: {f1_score(y_m_val.values, val_rf_multi_pred, average='macro', zero_division=0)*100:.2f}%)")

    log("======================================================================")
    log("BƯỚC 4: ĐÁNH GIÁ TRÊN TẬP TEST ĐÓNG BĂNG (15%) & LƯU ARTIFACTS")
    log("======================================================================")

    # Chấm điểm cuối cùng trên tập Test đóng băng
    test_rule_pred, lat_rule = measure_inference_latency_ms(rule_base.predict, X_test.values)
    m_test_rule = eval_binary_metrics(y_b_test.values, test_rule_pred, lat_rule)
    m_test_rule["train_time_sec"] = t_train_rule

    test_dt_pred, lat_dt = measure_inference_latency_ms(dt_bin_base.predict, X_test.values)
    m_test_dt = eval_binary_metrics(y_b_test.values, test_dt_pred, lat_dt)
    m_test_dt["train_time_sec"] = t_train_dt_bin

    test_rf_bin_raw, lat_rf_bin = measure_inference_latency_ms(rf_bin_pipe.predict, X_test.values)
    m_test_rf_bin = eval_binary_metrics(y_b_test.values, [0 if p == "benign" else 1 for p in test_rf_bin_raw], lat_rf_bin)
    m_test_rf_bin["train_time_sec"] = t_train_rf_bin

    test_iso_raw, lat_iso = measure_inference_latency_ms(iso_pipe.predict, X_test.values)
    m_test_iso = eval_binary_metrics(y_b_test.values, [0 if p == 1 else 1 for p in test_iso_raw], lat_iso)
    m_test_iso["train_time_sec"] = t_train_iso

    # Nhóm Multiclass 34 lớp (tách riêng, không đánh chung với Binary)
    test_dt_m_pred, lat_dt_m = measure_inference_latency_ms(dt_multi_base.predict, X_test.values)
    m_test_dt_multi = {
        "accuracy": round(float(accuracy_score(y_m_test.values, test_dt_m_pred)), 4),
        "macro_f1": round(float(f1_score(y_m_test.values, test_dt_m_pred, average="macro", zero_division=0)), 4),
        "train_time_sec": t_train_dt_multi,
        "inference_latency_ms": round(float(lat_dt_m), 4),
    }

    test_rf_m_pred, lat_rf_m = measure_inference_latency_ms(rf_multi_pipe.predict, X_test.values)
    m_test_rf_multi = {
        "accuracy": round(float(accuracy_score(y_m_test.values, test_rf_m_pred)), 4),
        "macro_f1": round(float(f1_score(y_m_test.values, test_rf_m_pred, average="macro", zero_division=0)), 4),
        "train_time_sec": t_train_rf_multi,
        "inference_latency_ms": round(float(lat_rf_m), 4),
        "confusion_matrix": confusion_matrix(y_m_test.values, test_rf_m_pred, labels=labels_list).tolist(),
    }

    log("--- [NHÓM 1: BÀI TOÁN PHÁT HIỆN BẤT THƯỜNG (BENIGN VS ATTACK) TRÊN TẬP TEST] ---")
    log(f"{'Mô hình & Vai trò':<34} | {'Acc':<7} | {'Prec':<7} | {'Recall':<7} | {'F1':<7} | {'FPR':<7} | {'Latency'}")
    log("-" * 92)
    for name, m in [
        ("Rule Threshold (Baseline)", m_test_rule),
        ("Decision Tree d=3 (Baseline ML)", m_test_dt),
        ("Isolation Forest (Unsupervised)", m_test_iso),
        ("Random Forest Binary (Supervised)", m_test_rf_bin),
    ]:
        log(
            f"{name:<34} | {m['accuracy']*100:5.2f}% | {m['precision']*100:5.2f}% | "
            f"{m['recall']*100:5.2f}% | {m['f1_score']*100:5.2f}% | {m['false_positive_rate']*100:5.2f}% | {m['inference_latency_ms']:.4f} ms"
        )

    log("")
    log("--- [NHÓM 2: BÀI TOÁN PHÂN LOẠI SÂU (34 LỚP TẤN CÔNG) TRÊN TẬP TEST] ---")
    log(f"• Decision Tree d=6 (Baseline 34 lớp): Acc={m_test_dt_multi['accuracy']*100:.2f}% | Macro F1={m_test_dt_multi['macro_f1']*100:.2f}% | Latency={m_test_dt_multi['inference_latency_ms']:.4f} ms")
    log(f"• Random Forest (34 lớp):              Acc={m_test_rf_multi['accuracy']*100:.2f}% | Macro F1={m_test_rf_multi['macro_f1']*100:.2f}% | Latency={m_test_rf_multi['inference_latency_ms']:.4f} ms")

    # Lưu artifacts nén gọn (compress=3 giúp tiết kiệm dung lượng thẻ nhớ Pi 5)
    joblib.dump(rf_bin_pipe, os.path.join(output_dir, "rf_binary_ciciot.joblib"), compress=3)
    joblib.dump(iso_pipe, os.path.join(output_dir, "if_ciciot.joblib"), compress=3)
    joblib.dump(rf_multi_pipe, os.path.join(output_dir, "rf_multiclass_ciciot.joblib"), compress=3)

    # Lưu tập test đại diện (lấy từ 15% Test đóng băng) phục vụ Replay
    test_df = X_test.copy()
    test_df["label"] = y_m_test.values
    sample_rows = [test_df[test_df["label"] == lbl].head(10) for lbl in labels_list]
    holdout_samples = pd.concat(sample_rows, ignore_index=True)
    holdout_samples.to_json(os.path.join(output_dir, "ciciot_test_samples.json"), orient="records")

    log(f"\n[OUTPUT] Đã nén và lưu 3 model Pipeline + {len(holdout_samples)} mẫu Test hold-out vào {output_dir}")

    metadata = {
        "dataset_name": "CICIoT2023 Subset",
        "total_samples": clean_stats["raw_rows"],
        "clean_samples": clean_stats["clean_rows"],
        "feature_count": len(feature_cols),
        "feature_names": feature_cols,
        "classes_count": len(labels_list),
        "labels": labels_list,
        "train_samples": int(len(X_train)),
        "val_samples": int(len(X_val)),
        "test_samples": int(len(X_test)),
        "random_seed": 42,
        "preprocessing": {
            "raw_rows": clean_stats["raw_rows"],
            "nan_inf_fixed": clean_stats["nan_inf_cells_fixed"],
            "duplicates_removed": clean_stats["duplicates_removed"],
            "clean_rows": clean_stats["clean_rows"],
            "split_strategy": "Stratified Split 70% Train / 15% Validation / 15% Test đóng băng",
            "train_test_overlap": overlap_count,
            "outlier_method": "QuantileClipper (1% - 99%) + RobustScaler (chỉ fit trên Train)",
            "clipped_cells": {"train": clipped_train, "val": clipped_val, "test": clipped_test},
        },
        "metrics": {
            "rule_baseline": m_test_rule,
            "dt_binary_baseline": m_test_dt,
            "binary_random_forest": m_test_rf_bin,
            "isolation_forest": m_test_iso,
            "dt_multiclass_baseline": m_test_dt_multi,
            "multiclass_random_forest": m_test_rf_multi,
        },
        "training_log": "\n".join(logs),
    }

    log("[SUCCESS] Hoàn tất huấn luyện & lưu ciciot_metadata.json!")
    metadata["training_log"] = "\n".join(logs)
    with open(os.path.join(output_dir, "ciciot_metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    log_path = os.path.join(BASE_DIR, "logs", "train_ciciot.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write(metadata["training_log"] + "\n")
    return metadata


if __name__ == "__main__":
    train_ciciot_models()
