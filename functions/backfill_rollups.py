import argparse
import datetime as dt
import json
import logging
import os
import time
from azure.core.exceptions import ResourceExistsError, HttpResponseError
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

from azure.data.tables import TableServiceClient, UpdateMode


ROLLUP_TABLE_NAME = "SensorHistoryRollups"
SOURCE_TABLE_NAME = "SensorData"
NUMERIC_FIELDS = ("humidity", "temperature", "battery", "moisture", "ph", "light")


def load_local_settings() -> None:
    settings_path = Path(__file__).resolve().parent / "local.settings.json"
    if not settings_path.exists():
        return

    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception as ex:
        logging.warning("Unable to read local.settings.json: %s", ex)
        return

    values = payload.get("Values") or {}
    for key, value in values.items():
        if not os.getenv(key) and isinstance(value, str) and value and not value.startswith("<"):
            os.environ[key] = value


def get_connection_string() -> str:
    load_local_settings()
    conn_str = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn_str:
        raise RuntimeError(
            "Missing storage connection string. Set STORAGE_CONNECTION_STRING or AzureWebJobsStorage to a real Azure Storage connection string."
        )
    return conn_str


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_timestamp(value: Any) -> Optional[dt.datetime]:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc).replace(microsecond=0)
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
            if numeric > 1e12:
                return dt.datetime.fromtimestamp(numeric / 1000.0, dt.timezone.utc).replace(microsecond=0)
            if numeric > 1e9:
                return dt.datetime.fromtimestamp(numeric, dt.timezone.utc).replace(microsecond=0)
        except Exception:
            return None
        return None
    try:
        s = str(value)
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


def to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(value)
    except Exception:
        return None


def get_device_ip(row: Dict[str, Any]) -> str:
    device_ip = row.get("deviceIp")
    if device_ip:
        return str(device_ip)
    partition = str(row.get("PartitionKey") or "unknown")
    return partition.replace("_", ".")


def iter_source_rows(client) -> Iterable[Dict[str, Any]]:
    query = ""
    select = ["PartitionKey", "RowKey", "timestamp", "deviceIp", *NUMERIC_FIELDS, "Timestamp"]
    return client.query_entities(query_filter=query, select=select)


def build_rollups(source_rows: Iterable[Dict[str, Any]]) -> Dict[Tuple[str, str, str], Dict[str, Any]]:
    buckets: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    for index, row in enumerate(source_rows, start=1):
        timestamp = parse_timestamp(row.get("timestamp") or row.get("Timestamp"))
        if not timestamp:
            continue

        device_ip = get_device_ip(row)
        for granularity in ("hour", "day", "month"):
            bucket_start = floor_to_bucket(timestamp, granularity)
            bucket_id = (device_ip, granularity, rollup_row_key(bucket_start))
            bucket = buckets.get(bucket_id)
            if not bucket:
                bucket = {
                    "deviceIp": device_ip,
                    "granularity": granularity,
                    "bucket_start": bucket_start,
                    "count": 0,
                    "sums": defaultdict(float),
                    "numeric_counts": defaultdict(int),
                }
                buckets[bucket_id] = bucket

            bucket["count"] += 1
            for field in NUMERIC_FIELDS:
                numeric = to_float(row.get(field))
                if numeric is None:
                    continue
                bucket["sums"][field] += numeric
                bucket["numeric_counts"][field] += 1

        if index % 1000 == 0:
            logging.info("Processed %s raw rows", index)

    return buckets


def average_from_bucket(bucket: Dict[str, Any], field: str) -> Optional[float]:
    count = bucket["numeric_counts"].get(field, 0)
    if not count:
        return None
    return round(bucket["sums"][field] / count, 2)


def write_rollups(table_client, buckets: Dict[Tuple[str, str, str], Dict[str, Any]]) -> None:
    now = now_iso()
    for index, bucket in enumerate(buckets.values(), start=1):
        bucket_start = bucket["bucket_start"]
        entity = {
            "PartitionKey": rollup_bucket_key(bucket["deviceIp"], bucket["granularity"]),
            "RowKey": rollup_row_key(bucket_start),
            "deviceIp": bucket["deviceIp"],
            "granularity": bucket["granularity"],
            "timestamp": rollup_row_key(bucket_start),
            "count": bucket["count"],
            "humidity": average_from_bucket(bucket, "humidity"),
            "temperature": average_from_bucket(bucket, "temperature"),
            "battery": average_from_bucket(bucket, "battery"),
            "moisture": average_from_bucket(bucket, "moisture"),
            "ph": average_from_bucket(bucket, "ph"),
            "light": average_from_bucket(bucket, "light"),
            "lastUpdated": now,
        }
        table_client.upsert_entity(mode=UpdateMode.REPLACE, entity=entity)
        if index % 1000 == 0:
            logging.info("Wrote %s rollup rows", index)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill SensorHistoryRollups from SensorData.")
    parser.add_argument("--keep-existing", action="store_true", help="Do not delete the existing rollup table before rebuilding.")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    conn_str = get_connection_string()
    service = TableServiceClient.from_connection_string(conn_str)
    source_client = service.get_table_client(SOURCE_TABLE_NAME)
    rollup_client = service.get_table_client(ROLLUP_TABLE_NAME)

    def create_table_with_retry(svc: TableServiceClient, name: str, max_retries: int = 10, base_delay: float = 1.0) -> None:
        last_exc = None
        for attempt in range(1, max_retries + 1):
            try:
                svc.create_table_if_not_exists(name)
                return
            except Exception as ex:
                last_exc = ex
                text = str(ex)
                if "TableBeingDeleted" in text or "being deleted" in text or "409" in text:
                    delay = base_delay * (2 ** (attempt - 1))
                    logging.warning(
                        "Table %s is being deleted; retrying in %s seconds (attempt %s/%s)", name, delay, attempt, max_retries
                    )
                    time.sleep(delay)
                    continue
                raise
        logging.error("Exceeded retries creating table %s", name)
        if last_exc:
            raise last_exc

    if not args.keep_existing:
        try:
            service.delete_table(ROLLUP_TABLE_NAME)
            logging.info("Deleted existing %s table", ROLLUP_TABLE_NAME)
        except Exception:
            pass
        create_table_with_retry(service, ROLLUP_TABLE_NAME, max_retries=12, base_delay=1.0)
        rollup_client = service.get_table_client(ROLLUP_TABLE_NAME)

    source_rows = iter_source_rows(source_client)
    buckets = build_rollups(source_rows)
    logging.info("Built %s rollup buckets", len(buckets))
    write_rollups(rollup_client, buckets)
    logging.info("Backfill complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())