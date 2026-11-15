"""Generate the synthetic AMI payload dataset used by VIDYUTSETU."""

import random
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd


def generate_synthetic_ami_data(n_samples=20000, seed=42):
    """Generate time-ordered, synthetic AMI payloads with learnable fault labels."""
    np.random.seed(seed)
    random.seed(seed)

    start_time = datetime(2026, 1, 1, 0, 0)
    meter_ids = [f"MET_BESCOM_{i:04d}" for i in range(1, 101)]

    fault_classes = [
        "VALID", "MISSING_FIELD", "WRONG_DATATYPE", "OUT_OF_RANGE_VALUE",
        "DUPLICATE_READING", "TIMESTAMP_DRIFT_OR_GAP", "NEGATIVE_OR_ROLLBACK_KWH", "UNIT_MISMATCH"
    ]
    fault_weights = [0.75, 0.04, 0.03, 0.04, 0.04, 0.04, 0.03, 0.03]

    def safe_float(value, default=0.0):
        try:
            if value is None or (isinstance(value, float) and np.isnan(value)):
                return float(default)
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    data = []
    meter_states = {
        meter_id: {
            "last_time": start_time,
            "last_kwh": float(np.random.uniform(100.0, 500.0)),
            "last_kvah": float(np.random.uniform(110.0, 550.0)),
            "last_voltage": float(np.random.uniform(220.0, 240.0)),
            "last_frequency": 50.0,
            "last_current": float(np.random.uniform(8.0, 16.0)),
            "last_pf": float(np.random.uniform(0.88, 0.99)),
            "last_timestamp": start_time,
            "last_record_index": None,
        }
        for meter_id in meter_ids
    }

    for i in range(n_samples):
        meter_id = np.random.choice(meter_ids)
        state = meter_states[meter_id]

        time_increment = timedelta(minutes=15)
        current_time = state["last_time"] + time_increment
        kwh_increment = float(np.random.exponential(scale=0.15))
        kvah_increment = kwh_increment * float(np.random.uniform(1.02, 1.10))

        base_kwh = state["last_kwh"] + kwh_increment
        base_kvah = state["last_kvah"] + kvah_increment
        base_voltage = float(np.random.normal(230.0, 3.5))
        base_current = float(np.random.normal(12.0, 2.0))
        base_pf = float(np.random.uniform(0.85, 0.99))
        base_freq = float(np.random.normal(50.0, 0.15))
        tamper = 0
        event_code = 0
        signal_strength = float(np.random.uniform(-90.0, -50.0))
        payload_size = int(np.random.normal(250, 20))

        fault_label = np.random.choice(fault_classes, p=fault_weights)

        is_anomaly = 0
        anomaly_type = "NONE"
        if np.random.rand() < 0.035:
            is_anomaly = 1
            anomaly_type = np.random.choice(["SPIKE", "FLATLINE", "SUDDEN_DROP"])
            if anomaly_type == "SPIKE":
                base_kwh += np.random.uniform(20.0, 50.0)
                base_voltage = np.random.uniform(280.0, 320.0)
            elif anomaly_type == "FLATLINE":
                base_kwh = state["last_kwh"]
                base_voltage = 0.0
                base_current = 0.0
            elif anomaly_type == "SUDDEN_DROP":
                base_voltage = np.random.uniform(100.0, 150.0)

        record = {
            "meter_id": meter_id,
            "timestamp": current_time.isoformat(),
            "kwh": float(base_kwh),
            "kvah": float(base_kvah),
            "voltage": float(base_voltage),
            "current": float(base_current),
            "power_factor": float(base_pf),
            "frequency": float(base_freq),
            "tamper_flag": tamper,
            "event_code": event_code,
            "interval_minutes": 15,
            "obis_code": "1.0.1.8.0.255",
            "signal_strength": float(signal_strength),
            "hes_batch_id": f"BATCH_HES_{i // 1000:03d}",
            "payload_size_bytes": payload_size,
            "fault_label": fault_label,
            "is_anomaly_label": is_anomaly,
            "anomaly_type": anomaly_type,
            "is_synthetic": 1,
        }

        if fault_label == "MISSING_FIELD":
            del_field = np.random.choice(["kwh", "voltage", "power_factor", "frequency"])
            record[del_field] = None

        elif fault_label == "WRONG_DATATYPE":
            record["voltage"] = np.random.choice(["230V_STRING", "N/A", "-", "230", "invalid"])
            record["frequency"] = np.random.choice(["50Hz", "60Hz", "abc"])

        elif fault_label == "OUT_OF_RANGE_VALUE":
            record["frequency"] = float(np.random.choice([999.9, -40.0, 65.0, 140.0]))
            record["voltage"] = float(np.random.choice([20.0, 440.0, -15.0, 600.0]))
            record["power_factor"] = float(np.random.choice([0.0, -0.2, 1.5, 2.3]))

        elif fault_label == "DUPLICATE_READING":
            if state["last_record_index"] is not None:
                previous_record = data[state["last_record_index"]]
                previous_record["fault_label"] = "DUPLICATE_READING"
                record = previous_record.copy()
            else:
                record["timestamp"] = state["last_time"].isoformat()
                record["kwh"] = float(state["last_kwh"])
                record["kvah"] = float(state["last_kvah"])
                record["voltage"] = float(state["last_voltage"])
                record["current"] = float(state["last_current"])
                record["power_factor"] = float(state["last_pf"])
                record["frequency"] = float(state["last_frequency"])

        elif fault_label == "TIMESTAMP_DRIFT_OR_GAP":
            drift_direction = np.random.choice(["future", "backward", "gap"])
            if drift_direction == "future":
                record["timestamp"] = (current_time + timedelta(days=np.random.randint(1, 14))).isoformat()
            elif drift_direction == "backward":
                record["timestamp"] = (state["last_timestamp"] - time_increment).isoformat()
            else:
                record["timestamp"] = (current_time + timedelta(hours=np.random.randint(3, 72))).isoformat()

        elif fault_label == "NEGATIVE_OR_ROLLBACK_KWH":
            rollback_value = max(0.0, state["last_kwh"] - float(np.random.uniform(5.0, 80.0)))
            record["kwh"] = float(np.random.choice([rollback_value, -abs(np.random.uniform(1.0, 30.0))]))
            record["kvah"] = float(max(0.0, state["last_kvah"] - float(np.random.uniform(8.0, 90.0))))

        elif fault_label == "UNIT_MISMATCH":
            record["kwh"] = float(base_kwh * 1000.0)
            record["kvah"] = float(base_kvah * 1000.0)

        try:
            emitted_timestamp = pd.Timestamp(record["timestamp"]).to_pydatetime()
        except (TypeError, ValueError):
            emitted_timestamp = current_time

        state["last_time"] = current_time
        state["last_timestamp"] = emitted_timestamp
        state["last_kwh"] = safe_float(record.get("kwh", base_kwh), state["last_kwh"])
        state["last_kvah"] = safe_float(record.get("kvah", base_kvah), state["last_kvah"])
        state["last_voltage"] = safe_float(record.get("voltage", base_voltage), state["last_voltage"])
        state["last_current"] = safe_float(record.get("current", base_current), state["last_current"])
        state["last_pf"] = safe_float(record.get("power_factor", base_pf), state["last_pf"])
        state["last_frequency"] = safe_float(record.get("frequency", base_freq), state["last_frequency"])
        state["last_record_index"] = len(data)
        data.append(record)

    return pd.DataFrame(data)


def main():
    dataset = generate_synthetic_ami_data()
    output_path = Path(__file__).resolve().parents[1] / "data" / "ami_payload_dataset_synthetic.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset.to_csv(output_path, index=False)

    timestamps = pd.to_datetime(dataset["timestamp"], errors="coerce")
    previous_timestamps = timestamps.groupby(dataset["meter_id"]).shift()
    backwards_rows = int((timestamps < previous_timestamps).sum())
    exact_duplicate_rows = int(dataset.duplicated().sum())

    print(f"Saved SYNTHETIC dataset to {output_path}")
    print("fault_label counts:")
    print(dataset["fault_label"].value_counts(dropna=False).to_string())
    print(f"Rows with backwards meter timestamps: {backwards_rows}")
    print(f"Exact duplicate rows: {exact_duplicate_rows}")


if __name__ == "__main__":
    main()
