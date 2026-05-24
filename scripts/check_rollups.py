# Run from repo root: python scripts/check_rollups.py
import os
import json
from pathlib import Path
from collections import Counter
from azure.data.tables import TableServiceClient

def load_local_settings():
    script_dir = Path(__file__).resolve().parent
    settings_path = script_dir / "local.settings.json"
    if not settings_path.exists():
        settings_path = script_dir.parent / "functions" / "local.settings.json"
    if not settings_path.exists():
        return
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return
    values = payload.get("Values") or {}
    for key, value in values.items():
        if not os.getenv(key) and isinstance(value, str) and value and not value.startswith("<"):
            os.environ[key] = value


def main():
    load_local_settings()
    print("check_rollups: starting...", flush=True)

    conn = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn:
        print("No STORAGE_CONNECTION_STRING or AzureWebJobsStorage environment variable found.", flush=True)
        raise SystemExit(1)

    try:
        svc = TableServiceClient.from_connection_string(conn)
        tc = svc.get_table_client("SensorHistoryRollups")
    except Exception as e:
        print("Failed to connect to Table service:", e, flush=True)
        raise

    counts = Counter()
    samples = {}
    try:
        for e in tc.query_entities(query_filter="", select=["PartitionKey","RowKey","granularity","timestamp","deviceIp"]):
            g = e.get("granularity") or "unknown"
            counts[g] += 1
            if g not in samples:
                samples[g] = {k: e.get(k) for k in ("PartitionKey","RowKey","timestamp","deviceIp")}
    except Exception as e:
        print("Failed querying SensorHistoryRollups:", e, flush=True)
        raise

    print("Rollup counts:", dict(counts), flush=True)
    print("Sample rows:", samples, flush=True)
    try:
        # breakdown by device
        by_device = {}
        for e in tc.query_entities(query_filter="", select=["granularity","deviceIp"]):
            g = e.get("granularity") or "unknown"
            d = e.get("deviceIp") or "unknown"
            by_device.setdefault(g, {})[d] = by_device.setdefault(g, {}).get(d, 0) + 1
        print("\nRollup counts by device (sample):", flush=True)
        for g, m in by_device.items():
            print(f"  {g}: {len(m)} devices, totals per-device sample: {dict(list(m.items())[:5])}", flush=True)
    except Exception as e:
        print("Failed to enumerate rollups by device:", e, flush=True)

    try:
        sd = svc.get_table_client("SensorData")
        partitions = {}
        sample_partitions = []
        count = 0
        for e in sd.query_entities(query_filter="", select=["PartitionKey","RowKey"]):
            pk = e.get("PartitionKey")
            if len(sample_partitions) < 20:
                sample_partitions.append(pk)
            count += 1
            if count >= 10000:
                # avoid scanning too long; stop after 10k rows
                break
        print("\nSensorData sample PartitionKeys (first 20 rows):", sample_partitions, flush=True)
        print("Scanned rows (capped at 10000):", count, flush=True)
    except Exception as e:
        print("Failed to query SensorData:", e, flush=True)


if __name__ == "__main__":
    main()