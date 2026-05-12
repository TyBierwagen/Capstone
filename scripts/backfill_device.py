import argparse
import datetime as dt
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict

from azure.data.tables import TableServiceClient, UpdateMode

NUMERIC_FIELDS = ("humidity", "temperature", "battery", "moisture", "ph", "light")
ROLLUP_TABLE_NAME = "SensorHistoryRollups"
SOURCE_TABLE_NAME = "SensorData"


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


def get_connection_string() -> str:
    load_local_settings()
    conn_str = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn_str:
        raise RuntimeError("Missing storage connection string. Set STORAGE_CONNECTION_STRING or AzureWebJobsStorage.")
    return conn_str


def parse_timestamp(value: Any):
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).replace(microsecond=0)
    try:
        s = str(value)
        # Normalize common redundant suffix like '+00:00Z' -> 'Z'
        if s.endswith('+00:00Z'):
            s = s.replace('+00:00Z', 'Z')
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc).replace(microsecond=0)
    except Exception:
        return None


def floor_to_bucket(timestamp: dt.datetime, granularity: str) -> dt.datetime:
    timestamp = timestamp.astimezone(dt.timezone.utc).replace(microsecond=0)
    if granularity == "hour":
        return timestamp.replace(minute=0, second=0)
    if granularity == "day":
        return timestamp.replace(hour=0, minute=0, second=0)
    if granularity == "month":
        return timestamp.replace(day=1, hour=0, minute=0, second=0)
    return timestamp


def rollup_bucket_key(device_ip: str, granularity: str) -> str:
    return f"{device_ip.replace('.', '_')}|{granularity}"


def rollup_row_key(bucket_start: dt.datetime) -> str:
    return bucket_start.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_float(value: Any):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def build_and_write_for_device(conn_str: str, partition_key: str) -> None:
    service = TableServiceClient.from_connection_string(conn_str)
    source = service.get_table_client(SOURCE_TABLE_NAME)
    rollup = service.get_table_client(ROLLUP_TABLE_NAME)

    select = ["PartitionKey", "RowKey", "timestamp", "deviceIp", *NUMERIC_FIELDS, "Timestamp"]
    query = f"PartitionKey eq '{partition_key}'"
    logging.info("Querying SensorData for partition %s", partition_key)
    rows = list(source.query_entities(query_filter=query, select=select))
    logging.info("Found %s raw rows for %s", len(rows), partition_key)

    buckets = {}
    for row in rows:
        timestamp = parse_timestamp(row.get("timestamp") or row.get("Timestamp"))
        if not timestamp:
            continue
        device_ip = row.get("deviceIp") or partition_key.replace('_', '.')
        for granularity in ("hour", "day", "month"):
            bucket_start = floor_to_bucket(timestamp, granularity)
            bucket_id = (device_ip, granularity, rollup_row_key(bucket_start))
            bucket = buckets.get(bucket_id)
            if not bucket:
                bucket = {"deviceIp": device_ip, "granularity": granularity, "bucket_start": bucket_start, "count": 0, "sums": defaultdict(float), "numeric_counts": defaultdict(int)}
                buckets[bucket_id] = bucket
            bucket["count"] += 1
            for field in NUMERIC_FIELDS:
                numeric = to_float(row.get(field))
                if numeric is None:
                    continue
                bucket["sums"][field] += numeric
                bucket["numeric_counts"][field] += 1

    logging.info("Built %s buckets; writing to rollup table...", len(buckets))
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    written = 0
    for bucket in buckets.values():
        bucket_start = bucket["bucket_start"]
        entity = {
            "PartitionKey": rollup_bucket_key(bucket["deviceIp"], bucket["granularity"]),
            "RowKey": rollup_row_key(bucket_start),
            "deviceIp": bucket["deviceIp"],
            "granularity": bucket["granularity"],
            "timestamp": rollup_row_key(bucket_start),
            "count": bucket["count"],
            "humidity": (round(bucket["sums"]["humidity"]/bucket["numeric_counts"].get("humidity",1),2) if bucket["numeric_counts"].get("humidity") else None),
            "temperature": (round(bucket["sums"]["temperature"]/bucket["numeric_counts"].get("temperature",1),2) if bucket["numeric_counts"].get("temperature") else None),
            "battery": (round(bucket["sums"]["battery"]/bucket["numeric_counts"].get("battery",1),2) if bucket["numeric_counts"].get("battery") else None),
            "moisture": (round(bucket["sums"]["moisture"]/bucket["numeric_counts"].get("moisture",1),2) if bucket["numeric_counts"].get("moisture") else None),
            "ph": (round(bucket["sums"]["ph"]/bucket["numeric_counts"].get("ph",1),2) if bucket["numeric_counts"].get("ph") else None),
            "light": (round(bucket["sums"]["light"]/bucket["numeric_counts"].get("light",1),2) if bucket["numeric_counts"].get("light") else None),
            "lastUpdated": now,
        }
        try:
            rollup.upsert_entity(mode=UpdateMode.REPLACE, entity=entity)
            written += 1
        except Exception as e:
            logging.warning("Failed to upsert rollup entity: %s", e)
    logging.info("Wrote %s rollup rows for partition %s", written, partition_key)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Backfill rollups for a single device partition.")
    parser.add_argument("partition", help="PartitionKey to backfill (e.g., 192_168_1_33)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        conn = get_connection_string()
    except Exception as e:
        logging.error("Missing connection string: %s", e)
        raise SystemExit(1)
    build_and_write_for_device(conn, args.partition)
