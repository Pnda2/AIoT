import os
import io
import csv
import json
import time
import random
import psutil
from contextlib import closing
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel
import paho.mqtt.publish as publish
import joblib
import numpy as np
import pandas as pd

import sys
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
from backend.app.db.database import get_db_connection, init_db
from pipeline.window_features import FEATURE_COLUMNS_14, compute_window_features_14

app = FastAPI(title="IoT Traffic Anomaly Detection Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Đường dẫn thư mục
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(PROJECT_ROOT, "models", "artifacts")
STATIC_DIR = os.path.join(BASE_DIR, "..", "static")
CAPTURES_DIR = os.path.join(PROJECT_ROOT, "data", "local_captures")
PROCESSED_CSV_PATH = os.path.join(PROJECT_ROOT, "data", "processed", "local_feature_windows.csv")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

# Nạp model artifacts của CICIoT2023 và Local ESP32
models_cache = {}

def _load_json_if_exists(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None

def load_models():
    try:
        models_cache["rf_multi"] = joblib.load(os.path.join(ARTIFACTS_DIR, "rf_multiclass_ciciot.joblib"))
        models_cache["rf_bin"] = joblib.load(os.path.join(ARTIFACTS_DIR, "rf_binary_ciciot.joblib"))
        models_cache["iso_forest"] = joblib.load(os.path.join(ARTIFACTS_DIR, "if_ciciot.joblib"))

        meta = _load_json_if_exists(os.path.join(ARTIFACTS_DIR, "ciciot_metadata.json"))
        if meta:
            models_cache["metadata"] = meta
        samples = _load_json_if_exists(os.path.join(ARTIFACTS_DIR, "ciciot_test_samples.json"))
        if samples:
            models_cache["test_samples"] = samples
        print("[Backend] Đã nạp thành công các model CICIoT2023 và metadata.")
    except Exception as e:
        print("[Backend] Chưa tìm thấy đầy đủ model CICIoT2023:", e)

    # Nạp model & report Local ESP32 (nếu đã huấn luyện)
    try:
        local_iso_path = os.path.join(ARTIFACTS_DIR, "local_iso_forest.joblib")
        if os.path.exists(local_iso_path):
            models_cache["local_iso"] = joblib.load(local_iso_path)
        local_bin_path = os.path.join(ARTIFACTS_DIR, "local_rf_binary.joblib")
        if os.path.exists(local_bin_path):
            models_cache["local_rf_binary"] = joblib.load(local_bin_path)
        local_sc_path = os.path.join(ARTIFACTS_DIR, "local_rf_scenario.joblib")
        if os.path.exists(local_sc_path):
            models_cache["local_rf_scenario"] = joblib.load(local_sc_path)
        for key, fname in [
            ("local_extract_report", "local_extract_report.json"),
            ("local_training_report", "local_training_report.json"),
            ("local_test_samples", "local_test_samples.json"),
        ]:
            obj = _load_json_if_exists(os.path.join(ARTIFACTS_DIR, fname))
            if obj is not None:
                models_cache[key] = obj
    except Exception as e:
        print("[Backend] Lưu ý khi nạp artifacts Local:", e)

# Khởi động DB và nạp models
init_db()
load_models()

# ====================================================================
# 1. API: CICIoT2023 LAB (Giao diện 01)
# ====================================================================
@app.get("/api/ciciot/info")
def get_ciciot_info():
    if "metadata" not in models_cache:
        raise HTTPException(status_code=404, detail="Chưa có dữ liệu metadata CICIoT2023")
    return models_cache["metadata"]

# ====================================================================
# 2. API: DEMO LAB REPLAY & SIMULATOR (Giao diện 03)
# ====================================================================
class ReplayRequest(BaseModel):
    attack_label: str
    model_type: str = "rf_multiclass" # rf_multiclass | rf_binary | iso_forest

@app.post("/api/ciciot/replay")
def replay_ciciot_sample(req: ReplayRequest):
    if "test_samples" not in models_cache:
        raise HTTPException(status_code=404, detail="Chưa có tập mẫu kiểm thử test samples")
        
    samples = models_cache["test_samples"]
    # Lọc các mẫu có ground truth đúng nhãn yêu cầu
    matching = [s for s in samples if s.get("label") == req.attack_label]
    
    if not matching:
        # Nếu không thấy đúng nhãn, bốc ngẫu nhiên
        sample = random.choice(samples)
    else:
        sample = random.choice(matching)
        
    ground_truth = sample["label"]
    feature_names = models_cache["metadata"]["feature_names"]
    
    # Tạo vector đặc trưng (loại bỏ nhãn ra khỏi X)
    x_vector = np.array([[sample.get(col, 0.0) for col in feature_names]])
    
    t0 = time.time()
    prediction = "UNKNOWN"
    score = None
    
    if req.model_type == "rf_multiclass" and "rf_multi" in models_cache:
        pred_raw = models_cache["rf_multi"].predict(x_vector)[0]
        prediction = str(pred_raw)
    elif req.model_type == "rf_binary" and "rf_bin" in models_cache:
        pred_raw = models_cache["rf_bin"].predict(x_vector)[0]
        prediction = str(pred_raw) # 'benign' hoặc 'attack'
    elif req.model_type == "iso_forest" and "iso_forest" in models_cache:
        pred_raw = models_cache["iso_forest"].predict(x_vector)[0]
        score = float(models_cache["iso_forest"].decision_function(x_vector)[0])
        prediction = "benign" if pred_raw == 1 else "anomaly"
        
    inference_ms = (time.time() - t0) * 1000
    
    # Đánh giá đúng sai
    is_correct = False
    if req.model_type == "rf_multiclass":
        is_correct = (prediction == ground_truth)
    elif req.model_type == "rf_binary":
        expected_bin = "benign" if ground_truth == "BenignTraffic" else "attack"
        is_correct = (prediction == expected_bin)
    elif req.model_type == "iso_forest":
        expected_anom = "benign" if ground_truth == "BenignTraffic" else "anomaly"
        is_correct = (prediction == expected_anom)

    return {
        "ground_truth": ground_truth,
        "prediction": prediction,
        "is_correct": is_correct,
        "model_used": req.model_type,
        "inference_ms": round(inference_ms, 3),
        "score": round(score, 4) if score is not None else None,
        "features_sample": {
            k: round(sample[k], 2) if isinstance(sample[k], float) else sample[k]
            for k in feature_names[:8]
        }
    }

class SimulateRequest(BaseModel):
    scenario: str # TH0 .. TH6

SIM_SCENARIO_MAP = {
    "TH0": "normal",
    "TH1": "high_rate",
    "TH2": "large_payload",
    "TH3": "reconnect",
    "TH4": "silence",
    "TH5": "burst",
    "TH6": "auth_fail",
}

def _sim_features_for_scenario(sc):
    if sc == "TH0":
        return {"packet_count": 2, "byte_count": 240, "packet_rate": 0.4, "byte_rate": 48.0, "len_mean": 120.0, "len_std": 8.0, "len_max": 136, "iat_mean": 2000.0, "iat_std": 45.0, "iat_max": 2060.0, "tcp_syn_count": 0, "tcp_fin_count": 0, "tcp_rst_count": 0, "is_empty_window": 0}
    if sc == "TH1":
        return {"packet_count": 75, "byte_count": 9000, "packet_rate": 15.0, "byte_rate": 1800.0, "len_mean": 120.0, "len_std": 10.0, "len_max": 140, "iat_mean": 65.0, "iat_std": 12.0, "iat_max": 110.0, "tcp_syn_count": 0, "tcp_fin_count": 0, "tcp_rst_count": 0, "is_empty_window": 0}
    if sc == "TH2":
        return {"packet_count": 2, "byte_count": 3100, "packet_rate": 0.4, "byte_rate": 620.0, "len_mean": 1550.0, "len_std": 15.0, "len_max": 1580, "iat_mean": 2000.0, "iat_std": 30.0, "iat_max": 2040.0, "tcp_syn_count": 0, "tcp_fin_count": 0, "tcp_rst_count": 0, "is_empty_window": 0}
    if sc == "TH3":
        return {"packet_count": 6, "byte_count": 720, "packet_rate": 1.2, "byte_rate": 144.0, "len_mean": 120.0, "len_std": 40.0, "len_max": 180, "iat_mean": 900.0, "iat_std": 400.0, "iat_max": 1800.0, "tcp_syn_count": 2, "tcp_fin_count": 2, "tcp_rst_count": 0, "is_empty_window": 0}
    if sc == "TH4":
        return {"packet_count": 0, "byte_count": 0, "packet_rate": 0.0, "byte_rate": 0.0, "len_mean": 0.0, "len_std": 0.0, "len_max": 0, "iat_mean": 0.0, "iat_std": 0.0, "iat_max": 0.0, "tcp_syn_count": 0, "tcp_fin_count": 0, "tcp_rst_count": 0, "is_empty_window": 1}
    if sc == "TH5":
        return {"packet_count": 20, "byte_count": 2400, "packet_rate": 4.0, "byte_rate": 480.0, "len_mean": 120.0, "len_std": 12.0, "len_max": 145, "iat_mean": 50.0, "iat_std": 35.0, "iat_max": 240.0, "tcp_syn_count": 0, "tcp_fin_count": 0, "tcp_rst_count": 0, "is_empty_window": 0}
    if sc == "TH6":
        return {"packet_count": 12, "byte_count": 840, "packet_rate": 2.4, "byte_rate": 168.0, "len_mean": 70.0, "len_std": 18.0, "len_max": 110, "iat_mean": 450.0, "iat_std": 180.0, "iat_max": 820.0, "tcp_syn_count": 4, "tcp_fin_count": 0, "tcp_rst_count": 4, "is_empty_window": 0}
    return None

@app.post("/api/simulator/trigger")
def trigger_software_simulator(req: SimulateRequest):
    """Mô phỏng hoặc replay tập Test hold-out 7 kịch bản Local ESP32 (hỗ trợ cả v1 6-feature và v2 14-feature)"""
    sc = req.scenario
    if sc not in SIM_SCENARIO_MAP:
        raise HTTPException(status_code=400, detail=f"Kịch bản không hợp lệ: {sc}")
    now = time.time()
    label_gt = SIM_SCENARIO_MAP[sc]

    m = models_cache.get("local_iso")
    if m is None:
        local_model_path = os.path.join(ARTIFACTS_DIR, "local_iso_forest.joblib")
        if os.path.exists(local_model_path):
            m = joblib.load(local_model_path)
            models_cache["local_iso"] = m

    n_feats = int(getattr(m, "n_features_in_", 6)) if m is not None else 6
    mode = "software_simulation"

    if n_feats == 14:
        test_samples = models_cache.get("local_test_samples") or []
        matching = [s for s in test_samples if s.get("scenario_label") == label_gt]
        if matching:
            sample = random.choice(matching)
            feats14 = {c: sample.get(c, 0.0) for c in FEATURE_COLUMNS_14}
            mode = "local_test_holdout"
        else:
            feats14 = _sim_features_for_scenario(sc)

        vec = np.array([[feats14[c] for c in FEATURE_COLUMNS_14]], dtype=float)
        if feats14["is_empty_window"] == 1:
            pred = "anomaly"
            score = -0.35
            rf_bin_pred = "anomaly"
        else:
            p = int(m.predict(vec)[0])
            score = float(m.decision_function(vec)[0])
            pred = "normal" if p == 1 else "anomaly"

            rf_bin = models_cache.get("local_rf_binary")
            if rf_bin is not None:
                p_bin = int(rf_bin.predict(vec)[0])
                rf_bin_pred = "anomaly" if p_bin == 1 else "normal"
            else:
                rf_bin_pred = pred

        scenario_pred = None
        rf_sc = models_cache.get("local_rf_scenario")
        if rf_sc is not None:
            scenario_pred = str(rf_sc.predict(vec)[0])

        display_feats = {
            c: round(float(feats14[c]), 2) if isinstance(feats14[c], float) else feats14[c]
            for c in FEATURE_COLUMNS_14
        }

        return {
            "mode": mode,
            "schema_version": "v2_14features",
            "scenario": sc,
            "ground_truth": label_gt,
            "model_prediction": pred,
            "iso_forest_pred": pred,
            "rf_binary_pred": rf_bin_pred,
            "scenario_prediction": scenario_pred,
            "rf_scenario_pred": scenario_pred,
            "anomaly_score": round(score, 4),
            "features": display_feats,
            "evaluated_at": now,
        }

    # Chế độ v1 (6 đặc trưng tương thích ngược trước khi thu thập phiên thực tối nay)
    feats14 = _sim_features_for_scenario(sc)
    feats6 = {
        "packet_count": feats14["packet_count"],
        "total_bytes": feats14["byte_count"],
        "mean_packet_len": feats14["len_mean"],
        "mean_iat": round(feats14["iat_mean"] / 1000.0, 4) if feats14["is_empty_window"] == 0 else 5.0,
        "packet_rate": feats14["packet_rate"],
        "byte_rate": feats14["byte_rate"],
    }
    pred = "normal"
    score = 0.1
    if m is not None:
        vec = np.array([[
            feats6["packet_count"],
            feats6["total_bytes"],
            feats6["mean_packet_len"],
            feats6["mean_iat"],
            feats6["packet_rate"],
            feats6["byte_rate"],
        ]], dtype=float)
        p = int(m.predict(vec)[0])
        score = float(m.decision_function(vec)[0])
        pred = "normal" if p == 1 else "anomaly"

    return {
        "mode": mode,
        "schema_version": "v1_6features",
        "scenario": sc,
        "ground_truth": label_gt,
        "model_prediction": pred,
        "anomaly_score": round(score, 4),
        "features": feats6,
        "evaluated_at": now,
    }

# ====================================================================
# 3. API: LIVE HARDWARE (Giao diện 04) & LOCAL DATASET (Giao diện 02)
# ====================================================================
@app.get("/api/devices")
def get_devices():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM devices ORDER BY id ASC")
    rows = cursor.fetchall()
    conn.close()
    
    now = time.time()
    devices = []
    for r in rows:
        d = dict(r)
        # Nếu quá 10s không thấy gửi tin -> đánh dấu offline
        if d["last_seen"] > 0 and (now - d["last_seen"]) > 10.0:
            d["status"] = "offline"
        devices.append(d)
    return devices

class DeviceControlRequest(BaseModel):
    scenario: str # TH0, TH1, TH2, TH3, TH4, TH5, TH6

@app.post("/api/devices/{device_id}/control")
def control_device(device_id: str, req: DeviceControlRequest):
    """Gửi lệnh MQTT điều khiển kịch bản xuống ESP32-S3 từ Dashboard"""
    topic = f"wievac/control/{device_id}"
    mqtt_ok = True
    try:
        publish.single(topic, req.scenario, hostname="127.0.0.1", port=1883)
    except Exception as e:
        mqtt_ok = False
        print(f"[MQTT] Không thể gửi lệnh tới {topic}: {e}")

    # Cập nhật scenario trong DB
    try:
        conn = get_db_connection()
        if device_id == "all":
            conn.cursor().execute("UPDATE devices SET current_scenario = ?", (req.scenario,))
        else:
            conn.cursor().execute("UPDATE devices SET current_scenario = ? WHERE id = ?", (req.scenario, device_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB] Lỗi cập nhật scenario thiết bị: {e}")

    if mqtt_ok:
        return {"status": "success", "message": f"Đã gửi lệnh {req.scenario} tới topic {topic}"}
    else:
        return {"status": "warning", "message": f"Đã ghi nhận kịch bản {req.scenario} (MQTT Broker không phản hồi)"}

ALERT_SEVERITY_ALIASES = {
    "HIGH": ("HIGH", "CRITICAL", "ERROR"),
    "MEDIUM": ("MEDIUM", "WARNING", "WARN"),
    "LOW": ("LOW", "INFO", "DEBUG"),
}
ALERT_FIELDS = (
    "id", "created_at", "device_key", "score", "predicted_label", "severity",
    "model_version", "alert_type", "reason_json", "status",
)


def _alert_filters(device_key, severity, search):
    clauses, params = [], []
    if device_key and device_key != "all":
        clauses.append("a.device_key = ?")
        params.append(device_key)
    if severity and severity.lower() != "all":
        names = ALERT_SEVERITY_ALIASES.get(severity.upper(), (severity.upper(),))
        placeholders = ", ".join("?" for _ in names)
        clauses.append(f"UPPER(a.severity) IN ({placeholders})")
        params.extend(names)
    if search and search.strip():
        clauses.append("""(
            INSTR(LOWER(a.device_key), ?) OR INSTR(LOWER(a.predicted_label), ?)
            OR INSTR(LOWER(a.model_version), ?) OR INSTR(LOWER(a.reason_json), ?)
            OR INSTR(LOWER(d.display_name), ?)
        )""")
        params.extend([search.strip().lower()] * 5)
    return " WHERE " + " AND ".join(clauses) if clauses else "", params


def _json_object(value):
    try:
        parsed = json.loads(value or "{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


@app.get("/api/alerts")
def get_alerts(
    limit: int = 50, offset: int = 0, device_key: str = None,
    severity: str = None, search: str = None, include_total: bool = False,
):
    where, params = _alert_filters(device_key, severity, search)
    query = " FROM alerts a LEFT JOIN devices d ON a.device_key = d.id" + where
    with closing(get_db_connection()) as conn:
        conn.execute("BEGIN")
        total = conn.execute("SELECT COUNT(*)" + query, params).fetchone()[0] if include_total else None
        rows = conn.execute(
            """SELECT a.*, d.display_name AS device_name, (
                SELECT w.feature_json FROM windows w
                WHERE w.device_key = a.device_key AND w.created_at = a.created_at
                ORDER BY w.id DESC LIMIT 1
            ) AS window_features""" + query + " ORDER BY a.created_at DESC, a.id DESC LIMIT ? OFFSET ?",
            (*params, 5000 if limit < 0 else min(limit, 5000), min(max(0, offset), 2**63 - 1)),
        ).fetchall()

    alerts = []
    for row in rows:
        item = dict(row)
        if item["reason_json"]:
            try:
                item["reason_json"] = json.loads(item["reason_json"])
            except (ValueError, TypeError):
                pass
        reasons = item["reason_json"] if isinstance(item["reason_json"], dict) else {}
        measured = _json_object(item.pop("window_features"))
        embedded = reasons.get("features")
        if isinstance(embedded, dict):
            measured.update(embedded)
        item["features"] = {key: measured[key] for key in FEATURE_COLUMNS_14 if key in measured}
        alerts.append(item)
    return {"total": total, "items": alerts} if include_total else alerts


def _csv_alert_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


@app.get("/api/alerts/export_csv")
def export_alerts_csv(device_key: str = None, severity: str = None, search: str = None):
    where, params = _alert_filters(device_key, severity, search)

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(ALERT_FIELDS)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        with closing(get_db_connection()) as conn:
            columns = ", ".join(f"a.{key}" for key in ALERT_FIELDS)
            query = " FROM alerts a LEFT JOIN devices d ON a.device_key = d.id"
            cursor = conn.execute(
                "SELECT " + columns + query + where + " ORDER BY a.created_at DESC, a.id DESC",
                params,
            )
            while batch := cursor.fetchmany(250):
                writer.writerows([_csv_alert_cell(value) for value in row] for row in batch)
                yield buffer.getvalue()
                buffer.seek(0)
                buffer.truncate()

    return StreamingResponse(
        rows(), media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="iot_alerts.csv"'},
    )


OBSERVATION_SECONDS = 5
# The collector flushes SQLite about every two seconds.
OBSERVATION_FLUSH_GRACE = 3
OBSERVATION_MAX_PACKETS = 5000
OBSERVATION_DEVICES = tuple(f"esp32_{index:02d}" for index in range(1, 7))
OBSERVATION_MODELS = ("local_iso", "local_rf_binary", "local_rf_scenario")
SCENARIO_MODEL_LABELS = {
    "normal": "TH0_NORMAL", "high_rate": "TH1_HIGH_RATE",
    "large_payload": "TH2_LARGE_PAYLOAD", "reconnect": "TH3_RECONNECT",
    "silence": "TH4_SILENCE", "burst": "TH5_BURST", "auth_fail": "TH6_AUTH_FAIL",
}


def _read_observation_packets(target, start, end, cursor=0, limit=250):
    params = OBSERVATION_DEVICES if target == "all" else (target,)
    placeholders = ", ".join("?" for _ in params)
    scope = f" AND device_key IN ({placeholders})"
    with closing(get_db_connection()) as conn:
        records = conn.execute(
            "SELECT * FROM observation_packets WHERE ts >= ? AND ts < ? AND id > ?"
            + scope + " ORDER BY id LIMIT ?",
            (start, end, cursor, *params, limit),
        ).fetchall()
    return [dict(row) for row in records]


def _observed_model_results(features):
    output = {}
    if features.get("is_empty_window") == 1:
        output["local_iso"] = {
            "status": "complete", "score": -0.35,
            "prediction": "anomaly",
        }
        output["local_rf_binary"] = {"status": "complete", "prediction": "anomaly"}
        output["local_rf_scenario"] = {"status": "complete", "prediction": "TH4_SILENCE"}
        return output

    vector = np.array([[features[name] for name in FEATURE_COLUMNS_14]], dtype=float)
    for key in OBSERVATION_MODELS:
        model = models_cache.get(key)
        width = getattr(model, "n_features_in_", None)
        if width is None:
            # Legacy pipelines start with QuantileClipper, which does not expose n_features_in_.
            width = next((step.n_features_in_ for _, step in getattr(model, "steps", ())
                          if hasattr(step, "n_features_in_")), None)
        if width != len(FEATURE_COLUMNS_14):
            output[key] = {"status": "unavailable"}
            continue
        try:
            predicted = model.predict(vector)[0]
            if key == "local_iso":
                score = float(model.decision_function(vector)[0])
                if not np.isfinite(score):
                    raise ValueError("Non-finite Isolation Forest score")
                output[key] = {
                    "status": "complete", "score": score,
                    "prediction": "anomaly" if predicted == -1 else "normal",
                }
            elif key == "local_rf_binary":
                output[key] = {"status": "complete", "prediction": "anomaly" if predicted == 1 else "normal"}
            else:
                label = str(predicted)
                output[key] = {"status": "complete", "prediction": SCENARIO_MODEL_LABELS.get(label, label)}
        except Exception:
            output[key] = {"status": "error"}
    return output


def _observation_result(target, packets, truncated):
    devices = OBSERVATION_DEVICES if target == "all" else (target,)
    by_device = {device: [] for device in devices}
    for packet in packets:
        flags = packet["tcp_flags"] or ""
        dev = packet.get("device_key")
        if dev in by_device:
            by_device[dev].append({
                "ts": packet["ts"], "len": packet["frame_len"],
                "syn": "S" in flags and "A" not in flags, "fin": "F" in flags, "rst": "R" in flags,
            })

    results = []
    for device, frames in by_device.items():
        if truncated:
            results.append({"device_key": device, "status": "truncated"})
            continue
        features = compute_window_features_14(frames, OBSERVATION_SECONDS)
        results.append({
            "device_key": device, "status": "complete", "features": features,
            "models": _observed_model_results(features),
        })
    return results


def _observation_event(event, data):
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/demo/observe")
def observe_packets(target_device: str = OBSERVATION_DEVICES[0]):
    """Quan sát lưu lượng trên Pi đang được Tshark ghi, theo một cửa sổ 5 giây."""
    if target_device != "all" and target_device not in OBSERVATION_DEVICES:
        raise HTTPException(status_code=422, detail="Thiết bị quan sát không hợp lệ")

    def events():
        start = time.time()
        end = start + OBSERVATION_SECONDS
        deadline = time.monotonic() + OBSERVATION_SECONDS + OBSERVATION_FLUSH_GRACE
        packets = []
        cursor = 0
        truncated = False
        yield _observation_event("ready", {"duration": OBSERVATION_SECONDS})
        try:
            while True:
                final_read = time.monotonic() >= deadline
                remaining = OBSERVATION_MAX_PACKETS + 1 - len(packets)
                limit = remaining if final_read else min(250, remaining)
                batch = _read_observation_packets(target_device, start, min(time.time(), end), cursor, limit)
                available = OBSERVATION_MAX_PACKETS - len(packets)
                truncated |= len(batch) > available
                if batch:
                    cursor = batch[-1]["id"]
                    packet_slice = batch[:available]
                    packets.extend(packet_slice)
                    if packet_slice:
                        yield _observation_event("packets", packet_slice)
                if final_read or truncated:
                    break
                time.sleep(0.4)

            yield _observation_event("result", {
                "packet_count": len(packets), "truncated": truncated,
                "devices": _observation_result(target_device, packets, truncated),
            })
        except Exception:
            yield _observation_event("failed", {"message": "Không đọc được dữ liệu Tshark trên gateway."})

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/windows")
def get_windows(limit: int = 60, device_key: str = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if device_key and device_key != "all":
        cursor.execute("SELECT * FROM windows WHERE device_key = ? ORDER BY created_at DESC LIMIT ?", (device_key, limit))
    else:
        cursor.execute("SELECT * FROM windows ORDER BY created_at DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    windows = []
    for r in rows:
        item = dict(r)
        if item.get("feature_json"):
            try:
                item["features"] = json.loads(item["feature_json"])
            except:
                pass
        windows.append(item)
    return windows

@app.get("/api/packets")
def get_packets(limit: int = 50):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM packet_logs ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/captures")
def list_captures(max_files: int = 5):
    os.makedirs(CAPTURES_DIR, exist_ok=True)
    all_files = []
    for name in os.listdir(CAPTURES_DIR):
        if name.endswith(".pcapng") or name.endswith(".pcap"):
            fpath = os.path.join(CAPTURES_DIR, name)
            try:
                st = os.stat(fpath)
                all_files.append((name, fpath, st.st_size, st.st_mtime))
            except Exception:
                pass

    # Sắp xếp theo modified time giảm dần (mới nhất lên đầu)
    all_files.sort(key=lambda x: x[3], reverse=True)

    # Tự động dọn dẹp các file cũ vượt quá max_files (đảm bảo luôn tối đa 5 file)
    for name, fpath, size, mtime in all_files[max_files:]:
        try:
            os.remove(fpath)
        except Exception:
            pass

    return [
        {
            "filename": name,
            "size_bytes": size,
            "modified_at": mtime
        }
        for name, fpath, size, mtime in all_files[:max_files]
    ]

@app.get("/api/captures/download/{filename}")
def download_capture(filename: str):
    safe_name = os.path.basename(filename)
    if safe_name != filename or not (safe_name.endswith(".pcapng") or safe_name.endswith(".pcap")):
        raise HTTPException(status_code=400, detail="Tên file không hợp lệ")
    fpath = os.path.join(CAPTURES_DIR, safe_name)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Không tìm thấy file capture")
    return FileResponse(fpath, media_type="application/octet-stream", filename=safe_name)

@app.get("/api/system/status")
def get_system_status():
    return {
        "cpu_usage_pct": psutil.cpu_percent(),
        "ram_usage_pct": psutil.virtual_memory().percent,
        "disk_usage_pct": psutil.disk_usage("/").percent if os.name != "nt" else psutil.disk_usage("C:\\").percent,
        "mqtt_broker": "Running (Port 1883)",
        "models_loaded": list(models_cache.keys())
    }

@app.get("/api/local/report")
def get_local_report():
    """Trả về báo cáo trích xuất 14 đặc trưng & kết quả huấn luyện Local ESP32."""
    extract_rep = _load_json_if_exists(os.path.join(ARTIFACTS_DIR, "local_extract_report.json"))
    train_rep = _load_json_if_exists(os.path.join(ARTIFACTS_DIR, "local_training_report.json"))
    local_iso = models_cache.get("local_iso")
    model_n_features = int(getattr(local_iso, "n_features_in_", 6)) if local_iso is not None else 6
    csv_exists = os.path.exists(PROCESSED_CSV_PATH)
    csv_info = None
    if csv_exists:
        st = os.stat(PROCESSED_CSV_PATH)
        csv_info = {"filename": os.path.basename(PROCESSED_CSV_PATH), "size_bytes": st.st_size, "modified_at": st.st_mtime}

    return {
        "schema_version": train_rep.get("schema_version") if train_rep else ("v2_14features" if model_n_features == 14 else "v1_6features"),
        "model_n_features": model_n_features,
        "extract_report": extract_rep,
        "training_report": train_rep,
        "processed_csv": csv_info,
    }

@app.get("/api/logs/windows")
def get_window_logs(limit: int = 30):
    """Nhật ký chi tiết từng chu kỳ trích xuất đặc trưng 5s từ Pi."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, ts, component, level, message, correlation_id FROM system_events WHERE component = 'window_extractor' ORDER BY id DESC LIMIT ?",
        (limit,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    total_windows = cursor.execute("SELECT COUNT(*) FROM windows").fetchone()[0]
    conn.close()
    return {"total_windows_db": total_windows, "logs": rows}


@app.get("/api/logs/files")
def list_log_files():
    """Liệt kê các file .log trích xuất, làm sạch và huấn luyện nằm trên Pi 5 (/home/pi/AIoT/logs)."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    files = []
    for name in sorted(os.listdir(LOGS_DIR)):
        if name.endswith(".log"):
            fpath = os.path.join(LOGS_DIR, name)
            if os.path.isfile(fpath):
                st = os.stat(fpath)
                files.append({"filename": name, "path": f"/home/pi/AIoT/logs/{name}", "size_bytes": st.st_size, "modified_at": st.st_mtime})
    return {"logs_dir": LOGS_DIR, "files": files}


@app.get("/api/logs/files/{filename}")
def read_or_download_log_file(filename: str):
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.endswith(".log"):
        raise HTTPException(status_code=400, detail="Tên file log không hợp lệ")
    fpath = os.path.join(LOGS_DIR, safe_name)
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Không tìm thấy file log")
    return FileResponse(fpath, media_type="text/plain; charset=utf-8", filename=safe_name)

@app.get("/api/windows/export-csv")
def export_windows_csv(limit: int = 500):
    """Xuất bảng cửa sổ 5s thực tế từ SQLite ra file CSV tải về."""
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT id, ts_start, ts_end, device_key, source, created_at, feature_json FROM windows ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    header = ["id", "device_key", "ts_start", "ts_end", "source", "scenario_label", "feature_source"] + FEATURE_COLUMNS_14
    writer.writerow(header)

    for r in rows:
        feats = {}
        try:
            feats = json.loads(r["feature_json"] or "{}")
        except Exception:
            pass
        row_out = [
            r["id"],
            r["device_key"],
            round(r["ts_start"], 3),
            round(r["ts_end"], 3),
            r["source"],
            feats.get("scenario_label", ""),
            feats.get("feature_source", "v1"),
        ]
        # Map cả v1 lẫn v2 cleanly khi xuất CSV
        compat_map = {
            "byte_count": feats.get("byte_count", feats.get("total_bytes", 0)),
            "len_mean": feats.get("len_mean", feats.get("mean_packet_len", 0.0)),
            "iat_mean": feats.get("iat_mean", round(float(feats.get("mean_iat", 0.0)) * 1000.0, 2)),
            "is_empty_window": feats.get("is_empty_window", 1 if feats.get("packet_count", 0) == 0 else 0),
        }
        for col in FEATURE_COLUMNS_14:
            val = feats.get(col, compat_map.get(col, 0))
            row_out.append(val)
        writer.writerow(row_out)

    csv_bytes = ("\ufeff" + buf.getvalue()).encode("utf-8")
    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="iot_live_windows_5s.csv"'},
    )

@app.get("/api/local/dataset/preview")
def preview_local_dataset(limit: int = 20):
    if not os.path.isfile(PROCESSED_CSV_PATH):
        return {"exists": False, "rows": [], "counts_by_scenario": {}}
    df = pd.read_csv(PROCESSED_CSV_PATH)
    counts = {str(k): int(v) for k, v in df["scenario_label"].value_counts().items()} if "scenario_label" in df.columns else {}
    return {
        "exists": True,
        "total_rows": int(len(df)),
        "columns": df.columns.tolist(),
        "counts_by_scenario": counts,
        "rows": df.head(limit).to_dict(orient="records"),
    }

@app.get("/api/local/dataset/csv")
def download_local_dataset_csv():
    if not os.path.isfile(PROCESSED_CSV_PATH):
        raise HTTPException(status_code=404, detail="Chưa có tập local_feature_windows.csv (hãy thu thập & chạy extract_features.py)")
    return FileResponse(PROCESSED_CSV_PATH, media_type="text/csv", filename="local_feature_windows.csv")

# ====================================================================
# 4. STATIC WEB DASHBOARD
# ====================================================================
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def serve_dashboard():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"message": "IoT Anomaly Detection Gateway API is running. UI index.html not found."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

