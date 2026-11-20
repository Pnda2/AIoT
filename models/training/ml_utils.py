import time
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)


class QuantileClipper(BaseEstimator, TransformerMixin):
    """Cắt gọt ngoại lệ theo phân vị [low_q, high_q]; chỉ fit trên tập Train để chống Data Leakage."""

    def __init__(self, low_q=0.01, high_q=0.99):
        self.low_q = low_q
        self.high_q = high_q

    def fit(self, X, y=None):
        arr = np.asarray(X, dtype=float)
        self.lower_ = np.quantile(arr, self.low_q, axis=0)
        self.upper_ = np.quantile(arr, self.high_q, axis=0)
        return self

    def transform(self, X):
        arr = np.asarray(X, dtype=float)
        clipped = np.clip(arr, self.lower_, self.upper_)
        self.last_clipped_cells_ = int(np.sum(clipped != arr))
        return clipped


class RuleThresholdBaseline:
    """Baseline luật thống kê đơn giản: học ngưỡng tối đa của mẫu sạch trên tập Train."""

    def __init__(self, key_indices, empty_idx=None, quantile=0.99):
        self.key_indices = list(key_indices)
        self.empty_idx = empty_idx
        self.quantile = quantile
        self.thresholds_ = {}

    def fit(self, X_benign):
        arr = np.asarray(X_benign, dtype=float)
        self.thresholds_ = {
            idx: float(np.quantile(arr[:, idx], self.quantile)) for idx in self.key_indices
        }
        return self

    def predict(self, X):
        arr = np.asarray(X, dtype=float)
        preds = np.zeros(len(arr), dtype=int)
        for i, row in enumerate(arr):
            if self.empty_idx is not None and row[self.empty_idx] >= 0.5:
                preds[i] = 1
                continue
            for idx, thr in self.thresholds_.items():
                if row[idx] > thr * 1.15:
                    preds[i] = 1
                    break
        return preds


def clean_dataframe(df, feature_cols, dedup_subset=None):
    """Làm sạch NaN/Inf và loại bỏ trùng lặp trước khi chia tập."""
    raw_rows = int(len(df))
    df_work = df.copy()

    # Kiểm tra và xử lý NaN / Inf
    numeric_df = df_work[feature_cols].replace([np.inf, -np.inf], np.nan)
    bad_cells = int(numeric_df.isna().sum().sum())
    if bad_cells > 0:
        numeric_df = numeric_df.fillna(0.0)
    df_work[feature_cols] = numeric_df

    # Loại bỏ trùng lặp trước khi split (Anti-Data Leakage)
    subset = dedup_subset if dedup_subset is not None else feature_cols
    before_dedup = len(df_work)
    df_work = df_work.drop_duplicates(subset=subset).reset_index(drop=True)
    duplicates_removed = int(before_dedup - len(df_work))

    stats = {
        "raw_rows": raw_rows,
        "nan_inf_cells_fixed": bad_cells,
        "duplicates_removed": duplicates_removed,
        "clean_rows": int(len(df_work)),
    }
    return df_work, stats


def eval_binary_metrics(y_true_bin, y_pred_bin, latency_ms=0.0):
    """Đo Accuracy, Precision, Recall, F1, FPR và Ma trận nhầm lẫn cho bài toán 0=Benign / 1=Attack."""
    acc = float(accuracy_score(y_true_bin, y_pred_bin))
    prec = float(precision_score(y_true_bin, y_pred_bin, pos_label=1, zero_division=0))
    rec = float(recall_score(y_true_bin, y_pred_bin, pos_label=1, zero_division=0))
    f1 = float(f1_score(y_true_bin, y_pred_bin, pos_label=1, zero_division=0))
    cm = confusion_matrix(y_true_bin, y_pred_bin, labels=[0, 1])
    tn, fp, fn, tp = cm.ravel()
    fpr = float(fp / (fp + tn)) if (fp + tn) > 0 else 0.0
    return {
        "accuracy": round(acc, 4),
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1_score": round(f1, 4),
        "false_positive_rate": round(fpr, 4),
        "inference_latency_ms": round(float(latency_ms), 4),
        "confusion_matrix": cm.tolist(),
    }


def measure_inference_latency_ms(predict_fn, X):
    t0 = time.time()
    preds = predict_fn(X)
    ms_per_sample = ((time.time() - t0) / max(1, len(X))) * 1000.0
    return preds, ms_per_sample

