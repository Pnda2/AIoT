import argparse
import json
import os
import sys
import time
import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest, RandomForestClassifier
from sklearn.metrics import accuracy_score, f1_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler
from sklearn.tree import DecisionTreeClassifier

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from pipeline.window_features import FEATURE_COLUMNS_14
from models.training.ml_utils import (
    QuantileClipper,
    RuleThresholdBaseline,
    clean_dataframe,
    eval_binary_metrics,
    measure_inference_latency_ms,
)

DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "data", "processed", "local_feature_windows.csv")
DEFAULT_EXTRACT_REPORT = os.path.join(BASE_DIR, "models", "artifacts", "local_extract_report.json")
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "models", "artifacts")
DEFAULT_LOG_OUT = os.path.join(BASE_DIR, "logs", "train_local.log")


def _time_based_split_per_scenario(df, train_ratio=0.70, val_ratio=0.15):
    """Chia chuỗi thời gian theo từng kịch bản (và từng batch nếu có nhiều đợt thu): 70% đầu Train | 15% giữa Val | 15% cuối Test."""
    train_parts, val_parts, test_parts = [], [], []
    split_details = []
    has_multi_batch = "batch" in df.columns and df["batch"].nunique() > 1

    for sc_label, grp in df.groupby("scenario_label", sort=True):
        subgroups = grp.groupby("batch", sort=True) if has_multi_batch else [(None, grp)]
        sc_total = sc_train = sc_val = sc_test = 0

        for _, sub_grp in subgroups:
            grp_sorted = sub_grp.sort_values(["window_start", "device_key"], kind="mergesort").reset_index(drop=True)
            n = len(grp_sorted)
            if n < 3:
                train_parts.append(grp_sorted)
                sc_total += n
                sc_train += n
                continue

            n_train = max(1, int(n * train_ratio))
            n_val = max(1, int(n * val_ratio))
            if n_train + n_val >= n:
                n_train = max(1, n - 2)
                n_val = 1
            n_test = n - n_train - n_val

            train_parts.append(grp_sorted.iloc[:n_train])
            val_parts.append(grp_sorted.iloc[n_train : n_train + n_val])
            test_parts.append(grp_sorted.iloc[n_train + n_val :])

            sc_total += n
            sc_train += n_train
            sc_val += n_val
            sc_test += n_test

        split_details.append({
            "scenario": sc_label,
            "total": sc_total,
            "train": sc_train,
            "val": sc_val,
            "test": sc_test,
        })

    df_train = pd.concat(train_parts, ignore_index=True) if train_parts else df.iloc[:0].copy()
    df_val = pd.concat(val_parts, ignore_index=True) if val_parts else df.iloc[:0].copy()
    df_test = pd.concat(test_parts, ignore_index=True) if test_parts else df.iloc[:0].copy()
    return df_train, df_val, df_test, split_details, has_multi_batch


def _dedup_local_preserve_empty(df, feature_cols):
    """Làm sạch NaN/Inf và chỉ loại trùng lặp trên cửa sổ có gói tin (giữ nguyên chuỗi im lặng TH4)."""
    raw_df = df.copy()
    numeric_df = raw_df[feature_cols].replace([np.inf, -np.inf], np.nan)
    bad_cells = int(numeric_df.isna().sum().sum())
    if bad_cells > 0:
        numeric_df = numeric_df.fillna(0.0)
    raw_df[feature_cols] = numeric_df

    non_empty = raw_df[raw_df["is_empty_window"] == 0].copy()
    empty_rows = raw_df[raw_df["is_empty_window"] == 1].copy()

    before_ne = len(non_empty)
    non_empty = non_empty.drop_duplicates(subset=feature_cols, keep="first")
    dup_removed = int(before_ne - len(non_empty))

    df_clean = pd.concat([non_empty, empty_rows], ignore_index=True)
    sort_cols = [c for c in ["batch", "window_start", "device_key"] if c in df_clean.columns]
    df_clean = df_clean.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)

    stats = {
        "raw_rows": int(len(df)),
        "nan_inf_cells_fixed": bad_cells,
        "duplicates_removed": dup_removed,
        "empty_silence_rows_preserved": int(len(empty_rows)),
        "clean_rows": int(len(df_clean)),
    }
    return df_clean, stats


def train_local_models(
    csv_path=DEFAULT_CSV_PATH,
    extract_report_path=DEFAULT_EXTRACT_REPORT,
    output_dir=DEFAULT_OUTPUT_DIR,
    random_state=42,
):
    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Không tìm thấy tập đặc trưng Local: {csv_path}")

    logs = []

    def log(msg=""):
        print(msg)
        logs.append(msg)

    t_pipeline_start = time.time()
    os.makedirs(output_dir, exist_ok=True)
    df_raw = pd.read_csv(csv_path)

    missing_cols = [c for c in FEATURE_COLUMNS_14 + ["binary_label", "scenario_label"] if c not in df_raw.columns]
    if missing_cols:
        raise ValueError(f"CSV thiếu các cột bắt buộc: {missing_cols}")

    log("======================================================================")
    log("BƯỚC 1: NẠP, LÀM SẠCH & CHIA TẬP THEO THỜI GIAN (LOCAL ESP32 - 14 ĐẶC TRƯNG)")
    log("======================================================================")
    log(f"[DATA] Nguồn dữ liệu: {csv_path}")
    log(f"[DATA] Số dòng ban đầu: {len(df_raw):,} cửa sổ 5s x {len(FEATURE_COLUMNS_14)} đặc trưng.")

    df_clean, clean_stats = _dedup_local_preserve_empty(df_raw, FEATURE_COLUMNS_14)
    log(f"[CLEAN] Đã xử lý {clean_stats['nan_inf_cells_fixed']:,} ô NaN/Inf.")
    log(
        f"[CLEAN] Đã loại bỏ {clean_stats['duplicates_removed']:,} mẫu trùng lặp trên các cửa sổ có lưu lượng "
        f"(giữ nguyên {clean_stats['empty_silence_rows_preserved']:,} cửa sổ im lặng TH4) -> Còn {clean_stats['clean_rows']:,} dòng sạch."
    )

    df_train, df_val, df_test, split_details, has_multi_batch = _time_based_split_per_scenario(df_clean)
    if df_train.empty or df_val.empty or df_test.empty:
        raise ValueError("Số mẫu sau làm sạch quá ít để chia đủ 3 tập Train / Val / Test (cần >= 3 mẫu/kịch bản).")

    # Kiểm tra Anti-Leakage trên các cửa sổ có lưu lượng (is_empty_window == 0)
    tr_ne = df_train[df_train["is_empty_window"] == 0][FEATURE_COLUMNS_14]
    te_ne = df_test[df_test["is_empty_window"] == 0][FEATURE_COLUMNS_14]
    tr_hashes = set(pd.util.hash_pandas_object(tr_ne, index=False)) if not tr_ne.empty else set()
    te_hashes = set(pd.util.hash_pandas_object(te_ne, index=False)) if not te_ne.empty else set()
    overlap_non_empty = len(tr_hashes & te_hashes)

    X_train = df_train[FEATURE_COLUMNS_14].copy()
    y_b_train = df_train["binary_label"].astype(int).values
    y_s_train = df_train["scenario_label"].astype(str).values

    X_val = df_val[FEATURE_COLUMNS_14].copy()
    y_b_val = df_val["binary_label"].astype(int).values
    y_s_val = df_val["scenario_label"].astype(str).values

    X_test = df_test[FEATURE_COLUMNS_14].copy()
    y_b_test = df_test["binary_label"].astype(int).values
    y_s_test = df_test["scenario_label"].astype(str).values

    # Kiểm tra QuantileClipper chỉ fit trên Train
    clipper_probe = QuantileClipper(0.01, 0.99).fit(X_train.values)
    clipper_probe.transform(X_train.values)
    clipped_train = clipper_probe.last_clipped_cells_
    clipper_probe.transform(X_val.values)
    clipped_val = clipper_probe.last_clipped_cells_
    clipper_probe.transform(X_test.values)
    clipped_test = clipper_probe.last_clipped_cells_

    log(f"1. Tập TRAIN (70% đầu):      {len(X_train):,} mẫu (Normal: {(y_b_train==0).sum():,} | Anomaly: {(y_b_train==1).sum():,})")
    log(f"2. Tập VALIDATION (15% giữa):{len(X_val):,} mẫu")
    log(f"3. Tập TEST ĐÓNG BĂNG (15%): {len(X_test):,} mẫu")
    log(f"[ANTI-LEAKAGE] Split tuần tự theo thời gian từng kịch bản | Trùng lặp non-empty Train-Test: {overlap_non_empty} mẫu.")
    log(f"[OUTLIER] QuantileClipper (1%-99%) & RobustScaler chỉ FIT trên Train -> Đã clip {clipped_train:,} ô Train, {clipped_val:,} ô Val, {clipped_test:,} ô Test.")

    if (y_b_train == 0).sum() == 0:
        raise ValueError("Tập Train không có mẫu Normal (TH0) để huấn luyện Isolation Forest!")

    log("======================================================================")
    log("BƯỚC 2: HUẤN LUYỆN BASELINE ĐỐI CHUẨN (FIT TRÊN TẬP TRAIN)")
    log("======================================================================")

    key_names = ["packet_count", "byte_count", "packet_rate", "byte_rate", "len_max", "tcp_syn_count"]
    key_indices = [FEATURE_COLUMNS_14.index(c) for c in key_names if c in FEATURE_COLUMNS_14]
    empty_idx = FEATURE_COLUMNS_14.index("is_empty_window")

    rule_base = RuleThresholdBaseline(key_indices=key_indices, empty_idx=empty_idx, quantile=0.99)
    rule_base.fit(X_train.values[y_b_train == 0])

    dt_bin_base = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", DecisionTreeClassifier(max_depth=3, random_state=random_state)),
    ])
    dt_bin_base.fit(X_train.values, y_b_train)

    dt_scenario_base = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", DecisionTreeClassifier(max_depth=5, random_state=random_state)),
    ])
    dt_scenario_base.fit(X_train.values, y_s_train)

    val_rule_preds, _ = measure_inference_latency_ms(rule_base.predict, X_val.values)
    val_rule_m = eval_binary_metrics(y_b_val, val_rule_preds)
    val_dt_preds, _ = measure_inference_latency_ms(dt_bin_base.predict, X_val.values)
    val_dt_m = eval_binary_metrics(y_b_val, val_dt_preds)
    val_dt_sc_acc = round(float(accuracy_score(y_s_val, dt_scenario_base.predict(X_val.values))), 4)

    log(f"-> [Baseline Rule + Watchdog]  Validation: Acc={val_rule_m['accuracy']*100:.2f}% | Prec={val_rule_m['precision']*100:.2f}% | Rec={val_rule_m['recall']*100:.2f}% | F1={val_rule_m['f1_score']*100:.2f}%")
    log(f"-> [Baseline DecisionTree d=3] Validation: Acc={val_dt_m['accuracy']*100:.2f}% | Prec={val_dt_m['precision']*100:.2f}% | Rec={val_dt_m['recall']*100:.2f}% | F1={val_dt_m['f1_score']*100:.2f}%")
    log(f"-> [Baseline DecisionTree 7TH] Validation: Acc={val_dt_sc_acc*100:.2f}% (gọi tên kịch bản)")

    log("======================================================================")
    log("BƯỚC 3: HUẤN LUYỆN CÁC MÔ HÌNH CHÍNH (LOCAL ESP32 PIPELINE)")
    log("======================================================================")

    # Model 1: Isolation Forest (Unsupervised — chỉ fit trên Train Normal TH0)
    # Lưu ý: KHÔNG gắn QuantileClipper(TH0) vào pipeline Isolation Forest vì sẽ cắt nhầm gai lưu lượng bất thường về vùng bình thường
    t0 = time.time()
    iso_pipe = Pipeline([
        ("scaler", RobustScaler()),
        ("clf", IsolationForest(n_estimators=100, contamination=0.05, random_state=random_state, n_jobs=-1)),
    ])
    iso_pipe.fit(X_train.values[y_b_train == 0])
    t_train_iso = round(time.time() - t0, 3)

    # Model 2: Random Forest Binary (Supervised Normal vs Anomaly)
    t0 = time.time()
    rf_bin_pipe = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", RandomForestClassifier(n_estimators=100, max_depth=14, random_state=random_state, n_jobs=-1)),
    ])
    rf_bin_pipe.fit(X_train.values, y_b_train)
    t_train_rf_bin = round(time.time() - t0, 3)

    # Model 3: Random Forest Scenario (Supervised 7 kịch bản TH0..TH6)
    t0 = time.time()
    rf_sc_pipe = Pipeline([
        ("clipper", QuantileClipper(0.01, 0.99)),
        ("scaler", RobustScaler()),
        ("clf", RandomForestClassifier(n_estimators=100, max_depth=14, random_state=random_state, n_jobs=-1)),
    ])
    rf_sc_pipe.fit(X_train.values, y_s_train)
    t_train_rf_sc = round(time.time() - t0, 3)

    val_iso_preds = np.where(iso_pipe.predict(X_val.values) == -1, 1, 0)
    val_iso_m = eval_binary_metrics(y_b_val, val_iso_preds)
    val_rf_preds = rf_bin_pipe.predict(X_val.values)
    val_rf_m = eval_binary_metrics(y_b_val, val_rf_preds)
    val_rf_sc_acc = round(float(accuracy_score(y_s_val, rf_sc_pipe.predict(X_val.values))), 4)

    log(f"-> [Isolation Forest (Chỉ học TH0)]  Val: Acc={val_iso_m['accuracy']*100:.2f}% | Prec={val_iso_m['precision']*100:.2f}% | Rec={val_iso_m['recall']*100:.2f}% | F1={val_iso_m['f1_score']*100:.2f}% (Train {t_train_iso}s)")
    log(f"-> [Random Forest Binary]            Val: Acc={val_rf_m['accuracy']*100:.2f}% | Prec={val_rf_m['precision']*100:.2f}% | Rec={val_rf_m['recall']*100:.2f}% | F1={val_rf_m['f1_score']*100:.2f}% (Train {t_train_rf_bin}s)")
    log(f"-> [Random Forest 7 Kịch bản]        Val: Acc={val_rf_sc_acc*100:.2f}% (Train {t_train_rf_sc}s)")

    log("======================================================================")
    log("BƯỚC 4: ĐÁNH GIÁ CHÍNH THỨC TRÊN TẬP TEST ĐÓNG BĂNG (15% CUỐI)")
    log("======================================================================")

    test_rule_preds, lat_rule = measure_inference_latency_ms(rule_base.predict, X_test.values)
    m_test_rule = eval_binary_metrics(y_b_test, test_rule_preds, lat_rule)
    m_test_rule["train_time_s"] = 0.01

    test_dt_preds, lat_dt = measure_inference_latency_ms(dt_bin_base.predict, X_test.values)
    m_test_dt = eval_binary_metrics(y_b_test, test_dt_preds, lat_dt)

    test_iso_raw, lat_iso = measure_inference_latency_ms(iso_pipe.predict, X_test.values)
    test_iso_bin = np.where(test_iso_raw == -1, 1, 0)
    m_test_iso = eval_binary_metrics(y_b_test, test_iso_bin, lat_iso)
    m_test_iso["train_time_s"] = t_train_iso

    test_rf_preds, lat_rf = measure_inference_latency_ms(rf_bin_pipe.predict, X_test.values)
    m_test_rf = eval_binary_metrics(y_b_test, test_rf_preds, lat_rf)
    m_test_rf["train_time_s"] = t_train_rf_bin

    # Bài toán 2: Nhận diện 7 kịch bản (Local Scenario)
    test_dt_sc_preds, lat_dt_sc = measure_inference_latency_ms(dt_scenario_base.predict, X_test.values)
    m_test_dt_sc = {
        "accuracy": round(float(accuracy_score(y_s_test, test_dt_sc_preds)), 4),
        "macro_f1": round(float(f1_score(y_s_test, test_dt_sc_preds, average="macro", zero_division=0)), 4),
        "inference_latency_ms": round(float(lat_dt_sc), 4),
    }

    test_rf_sc_preds, lat_rf_sc = measure_inference_latency_ms(rf_sc_pipe.predict, X_test.values)
    m_test_rf_sc = {
        "accuracy": round(float(accuracy_score(y_s_test, test_rf_sc_preds)), 4),
        "macro_f1": round(float(f1_score(y_s_test, test_rf_sc_preds, average="macro", zero_division=0)), 4),
        "inference_latency_ms": round(float(lat_rf_sc), 4),
        "train_time_s": t_train_rf_sc,
    }

    # Tỷ lệ phát hiện theo từng kịch bản của Isolation Forest trên tập Test
    scenario_breakdown = []
    for sc in sorted(np.unique(y_s_test)):
        mask = y_s_test == sc
        total_sc = int(mask.sum())
        flagged_iso = int((test_iso_bin[mask] == 1).sum())
        flagged_rf = int((test_rf_preds[mask] == 1).sum())
        rf_sc_correct = int((test_rf_sc_preds[mask] == sc).sum())
        scenario_breakdown.append({
            "scenario_label": sc,
            "test_samples": total_sc,
            "iso_flagged_count": flagged_iso,
            "iso_flagged_rate": round(flagged_iso / max(1, total_sc), 4),
            "rf_bin_flagged_rate": round(flagged_rf / max(1, total_sc), 4),
            "rf_scenario_acc": round(rf_sc_correct / max(1, total_sc), 4),
        })

    log("")
    log("--- [NHÓM 1: PHÁT HIỆN BẤT THƯỜNG MẠCH ESP32 (0=Normal vs 1=Anomaly) TRÊN TEST] ---")
    log(f"{'MÔ HÌNH':<32} | {'ACC':>6} | {'PREC':>6} | {'REC':>6} | {'F1':>6} | {'FPR':>6} | {'LATENCY':>9}")
    log("-" * 82)
    for name, m in [
        ("Rule + Watchdog (Baseline)", m_test_rule),
        ("Decision Tree d=3 (Baseline)", m_test_dt),
        ("Isolation Forest (Edge Runtime)", m_test_iso),
        ("Random Forest Binary", m_test_rf),
    ]:
        log(
            f"{name:<32} | {m['accuracy']*100:5.2f}% | {m['precision']*100:5.2f}% | "
            f"{m['recall']*100:5.2f}% | {m['f1_score']*100:5.2f}% | {m['false_positive_rate']*100:5.2f}% | {m['inference_latency_ms']:.4f} ms"
        )

    log("")
    log("--- [NHÓM 2: NHẬN DIỆN KỊCH BẢN CHI TIẾT (TH0..TH6) TRÊN TEST] ---")
    log(f"• Decision Tree d=5 (Baseline): Acc={m_test_dt_sc['accuracy']*100:.2f}% | Macro F1={m_test_dt_sc['macro_f1']*100:.2f}% | Latency={m_test_dt_sc['inference_latency_ms']:.4f} ms")
    log(f"• Random Forest Scenario:       Acc={m_test_rf_sc['accuracy']*100:.2f}% | Macro F1={m_test_rf_sc['macro_f1']*100:.2f}% | Latency={m_test_rf_sc['inference_latency_ms']:.4f} ms")

    # Lưu artifacts nén gọn (compress=3)
    joblib.dump(iso_pipe, os.path.join(output_dir, "local_iso_forest.joblib"), compress=3)
    joblib.dump(rf_bin_pipe, os.path.join(output_dir, "local_rf_binary.joblib"), compress=3)
    joblib.dump(rf_sc_pipe, os.path.join(output_dir, "local_rf_scenario.joblib"), compress=3)

    # Lưu hold-out test samples từ 15% Test đóng băng cho Simulator Replay
    sample_parts = [df_test[df_test["scenario_label"] == sc].head(15) for sc in sorted(df_test["scenario_label"].unique())]
    holdout_df = pd.concat(sample_parts, ignore_index=True) if sample_parts else df_test.head(50)
    holdout_df.to_json(os.path.join(output_dir, "local_test_samples.json"), orient="records", force_ascii=False)

    extract_summary = None
    if extract_report_path and os.path.exists(extract_report_path):
        try:
            with open(extract_report_path, "r", encoding="utf-8") as f:
                extract_summary = json.load(f)
        except Exception:
            extract_summary = None

    scenarios_list = sorted(df_clean["scenario_label"].unique().tolist())
    split_desc = (
        "Time-Based Split trong từng (batch, kịch bản): 70% đầu Train / 15% giữa Val / 15% cuối Test đóng băng"
        if has_multi_batch
        else "Time-Based Split theo từng kịch bản: 70% đầu Train / 15% giữa Val / 15% cuối Test đóng băng"
    )
    report = {
        "schema_version": "v2_14features",
        "trained_at": time.time(),
        "duration_s": round(time.time() - t_pipeline_start, 2),
        "dataset_name": "Local ESP32-S3 Real Sessions (14 Features)",
        "csv_path": csv_path,
        "feature_count": len(FEATURE_COLUMNS_14),
        "feature_columns": FEATURE_COLUMNS_14,
        "scenarios": scenarios_list,
        "train_samples": int(len(X_train)),
        "val_samples": int(len(X_val)),
        "test_samples": int(len(X_test)),
        "preprocessing": {
            "raw_rows": clean_stats["raw_rows"],
            "nan_inf_fixed": clean_stats["nan_inf_cells_fixed"],
            "duplicates_removed": clean_stats["duplicates_removed"],
            "empty_silence_rows_preserved": clean_stats["empty_silence_rows_preserved"],
            "clean_rows": clean_stats["clean_rows"],
            "split_strategy": split_desc,
            "split_per_scenario": split_details,
            "train_test_overlap_non_empty": overlap_non_empty,
            "outlier_method": "QuantileClipper (1% - 99%) + RobustScaler (chỉ fit trên Train)",
            "clipped_cells": {"train": clipped_train, "val": clipped_val, "test": clipped_test},
        },
        "metrics": {
            "rule_baseline": m_test_rule,
            "dt_binary_baseline": m_test_dt,
            "isolation_forest": m_test_iso,
            "rf_binary": m_test_rf,
            "dt_scenario_baseline": m_test_dt_sc,
            "rf_scenario": m_test_rf_sc,
        },
        "scenario_breakdown": scenario_breakdown,
        "extract_summary": extract_summary,
        "training_log": "\n".join(logs),
    }

    report_out = os.path.join(output_dir, "local_training_report.json")
    with open(report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    log(f"\n[OUTPUT] Đã nén lưu 3 model Pipeline + {len(holdout_df)} mẫu Test hold-out vào {output_dir}")
    log("[SUCCESS] Hoàn tất huấn luyện Local ESP32 & lưu local_training_report.json!")
    report["training_log"] = "\n".join(logs)
    with open(report_out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    os.makedirs(os.path.dirname(DEFAULT_LOG_OUT), exist_ok=True)
    with open(DEFAULT_LOG_OUT, "w", encoding="utf-8") as f:
        f.write(report["training_log"] + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Huấn luyện mô hình Local ESP32 trên 14 đặc trưng cửa sổ 5s")
    parser.add_argument("--csv", default=DEFAULT_CSV_PATH)
    parser.add_argument("--extract-report", default=DEFAULT_EXTRACT_REPORT)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    train_local_models(args.csv, args.extract_report, args.output_dir, args.seed)
