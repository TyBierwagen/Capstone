import azure.functions as func
import datetime
import json
import logging
import os
import re
import uuid
from typing import Optional, Any, Dict
from azure.data.tables import TableServiceClient, UpdateMode

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import traceback
from functools import wraps
import math
from time import time

app = func.FunctionApp()

# Storage Configuration
conn_str = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
if not conn_str:
    logging.error("No Azure Storage connection string configured. Set STORAGE_CONNECTION_STRING or AzureWebJobsStorage to a real Azure Storage account.")
try:
    table_service = TableServiceClient.from_connection_string(conn_str) if conn_str else None
except Exception as ex:
    logging.error("Failed to initialize TableServiceClient: %s", ex)
    table_service = None

_ENSURED_TABLES: set[str] = set()

def get_table_client(table_name: str):
    if not table_service:
        return None
    if table_name not in _ENSURED_TABLES:
        try:
            table_service.create_table_if_not_exists(table_name)
            _ENSURED_TABLES.add(table_name)
        except Exception as ex:
            logging.warning("Unable to ensure table %s exists: %s", table_name, ex)
    return table_service.get_table_client(table_name)


ROLLUP_TABLE_NAME = "SensorHistoryRollups"
ROLLUP_FIELD_MAP = {
    "hour": "hour",
    "day": "day",
    "month": "month",
}


def get_rollup_table_client():
    return get_table_client(ROLLUP_TABLE_NAME)

# Simple in-memory cache for rollup responses to reduce repeated query cost
# Keyed by (device_ip, timescale, start, end) -> (ts, rows)
_ROLLUP_CACHE: Dict[tuple, tuple[float, list]] = {}
_ROLLUP_CACHE_TTL = 30.0  # seconds


def floor_to_bucket(dt: datetime.datetime, granularity: str) -> datetime.datetime:
    dt = dt.replace(microsecond=0)
    if granularity == "hour":
        return dt.replace(minute=0, second=0)
    if granularity == "day":
        return dt.replace(hour=0, minute=0, second=0)
    if granularity == "month":
        return dt.replace(day=1, hour=0, minute=0, second=0)
    return dt


def rollup_bucket_key(device_ip: str, granularity: str) -> str:
    return f"{device_ip.replace('.', '_')}|{granularity}"


def rollup_row_key(bucket_start: datetime.datetime) -> str:
    return bucket_start.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def rollup_partition_and_row(device_ip: str, bucket_start: datetime.datetime, granularity: str) -> tuple[str, str]:
    return rollup_bucket_key(device_ip, granularity), rollup_row_key(bucket_start)


def get_rollup_granularity(timescale: str) -> Optional[str]:
    if timescale == "1d":
        return "hour"
    if timescale == "1m":
        return "hour"
    if timescale in ("1y", "all"):
        return "day"
    return None


def get_rollup_granularities(timescale: str) -> list:
    """Return ordered list of rollup granularities to try for a given timescale.
    Prefer finer-grained rollups first, then fall back to coarser ones if empty.
    """
    if timescale == "1d":
        return ["hour", "day"]
    if timescale == "1m":
        return ["hour", "day", "month"]
    if timescale in ("1y", "all"):
        return ["day", "month"]
    return []


def merge_numeric(current_value, new_value, current_count: int) -> tuple[Optional[float], int]:
    try:
        numeric = float(new_value)
    except Exception:
        return current_value, current_count

    if current_value is None:
        return numeric, current_count + 1

    try:
        existing = float(current_value)
    except Exception:
        existing = 0.0

    total = existing * current_count + numeric
    return total / (current_count + 1), current_count + 1


def update_rollup_entry(entry: dict, granularity: str) -> None:
    client = get_rollup_table_client()
    if not client:
        return

    timestamp_raw = entry.get("timestamp")
    if not timestamp_raw:
        return

    try:
        entry_dt = datetime.datetime.fromisoformat(str(timestamp_raw).replace("Z", "+00:00"))
    except Exception:
        return

    bucket_start = floor_to_bucket(entry_dt, granularity)
    partition_key, row_key = rollup_partition_and_row(entry.get("deviceIp", "unknown"), bucket_start, granularity)

    try:
        existing = client.get_entity(partition_key=partition_key, row_key=row_key)
    except Exception:
        existing = None

    counts = int(existing.get("count", 0)) if existing else 0
    humidity, humidity_count = merge_numeric(existing.get("humidity") if existing else None, entry.get("humidity"), counts)
    temperature, temperature_count = merge_numeric(existing.get("temperature") if existing else None, entry.get("temperature"), counts)
    battery, battery_count = merge_numeric(existing.get("battery") if existing else None, entry.get("battery"), counts)
    moisture, moisture_count = merge_numeric(existing.get("moisture") if existing else None, entry.get("moisture"), counts)
    ph, ph_count = merge_numeric(existing.get("ph") if existing else None, entry.get("ph"), counts)
    light, light_count = merge_numeric(existing.get("light") if existing else None, entry.get("light"), counts)

    next_count = max(humidity_count, temperature_count, battery_count, moisture_count, ph_count, light_count, counts + 1)
    rollup_entity = {
        "PartitionKey": partition_key,
        "RowKey": row_key,
        "deviceIp": entry.get("deviceIp"),
        "granularity": granularity,
        "timestamp": rollup_row_key(bucket_start),
        "count": next_count,
        "humidity": humidity,
        "temperature": temperature,
        "battery": battery,
        "moisture": moisture,
        "ph": ph,
        "light": light,
        "lastUpdated": now_iso(),
    }

    try:
        client.upsert_entity(mode=UpdateMode.REPLACE, entity=rollup_entity)
    except Exception as e:
        logging.warning("Failed to update %s rollup: %s", granularity, e)


def update_rollups(entry: dict) -> None:
    for granularity in ("hour", "day", "month"):
        update_rollup_entry(entry, granularity)

def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def format_timedelta(seconds: float) -> str:
    """Return a human-friendly duration string for the given seconds."""
    try:
        s = int(round(seconds))
    except Exception:
        return "unknown"

    days, rem = divmod(s, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or (days and (minutes or secs)):
        parts.append(f"{hours}h")
    if minutes or (hours and secs):
        parts.append(f"{minutes}m")
    parts.append(f"{secs}s")

    return " ".join(parts)


def sanitize_timestamp(value):
    """Normalize timestamp inputs to an ISO string with a trailing 'Z'.
    Accepts datetime, ISO strings, and epoch seconds or milliseconds (int/float)."""
    if not value:
        return None
    # Numeric epochs (seconds or milliseconds)
    if isinstance(value, (int, float)):
        try:
            v = float(value)
            if v > 1e12:
                dt = datetime.datetime.fromtimestamp(v / 1000.0, datetime.timezone.utc)
            elif v > 1e9:
                dt = datetime.datetime.fromtimestamp(v, datetime.timezone.utc)
            else:
                return None
            return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return None
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        v = value.strip()
        v = v.replace("+00:00Z", "Z").replace("+00:00", "Z")
        # If it's a pure 10-digit epoch in seconds, convert
        if re.match(r'^\d{10}$', v):
            try:
                dt = datetime.datetime.fromtimestamp(int(v), datetime.timezone.utc)
                return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            except Exception:
                pass
        # If it's a pure 13-digit epoch in milliseconds, convert
        if re.match(r'^\d{13}$', v):
            try:
                dt = datetime.datetime.fromtimestamp(int(v) / 1000.0, datetime.timezone.utc)
                return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            except Exception:
                pass
        try:
            parsed = datetime.datetime.fromisoformat(v.replace("Z", "+00:00"))
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except Exception:
            return v
    try:
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return str(value)


def json_response(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json")


def safe_function(handler):
    @wraps(handler)
    def wrapper(req: func.HttpRequest):
        try:
            return handler(req)
        except Exception as ex:
            logging.exception("Unhandled exception in function %s", handler.__name__)
            return json_response({"error": "Internal server error", "details": str(ex)}, status=500)
    return wrapper


def parse_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def generate_device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:16]}"


def persist_device(device_id: str, ip_address: str, port: int, device_type: str, last_seen: Optional[str] = None) -> dict:
    now = now_iso()
    client = get_table_client("Devices")
    
    # Try to get existing
    existing = None
    if client:
        try:
            existing = client.get_entity(partition_key="Device", row_key=ip_address.replace(".", "_"))
        except:
            pass

    registered_at = existing["registeredAt"] if existing else now
    last_seen_value = last_seen or now
    
    device_info = {
        "PartitionKey": "Device",
        "RowKey": ip_address.replace(".", "_"),
        "id": device_id,
        "ip": ip_address,
        "port": port,
        "type": device_type,
        "registeredAt": registered_at,
        "lastSeen": last_seen_value,
        "status": "active",
    }
    
    if client:
        client.upsert_entity(mode=UpdateMode.REPLACE, entity=device_info)
    
    return device_info


def store_sensor_entry(payload: dict) -> dict:
    # Prefer device-provided timestamp when valid; otherwise use server time.
    device_ts_raw = payload.get("timestamp")
    parsed_dt = None
    if device_ts_raw:
        try:
            if isinstance(device_ts_raw, (int, float)):
                v = float(device_ts_raw)
                if v > 1e12:
                    parsed_dt = datetime.datetime.fromtimestamp(v / 1000.0, datetime.timezone.utc)
                elif v > 1e9:
                    parsed_dt = datetime.datetime.fromtimestamp(v, datetime.timezone.utc)
                else:
                    parsed_dt = None
            elif isinstance(device_ts_raw, str):
                s = device_ts_raw.strip().replace("+00:00Z", "Z").replace("+00:00", "Z")
                if re.match(r'^\d{10}$', s):
                    parsed_dt = datetime.datetime.fromtimestamp(int(s), datetime.timezone.utc)
                else:
                    try:
                        parsed_dt = datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
                    except Exception:
                        parsed_dt = None
        except Exception:
            parsed_dt = None

    if parsed_dt:
        ts_dt = parsed_dt.replace(microsecond=0)
        timestamp = ts_dt.isoformat().replace("+00:00", "Z")
        now = ts_dt
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
        timestamp = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    device_ip = payload.get("deviceIp", "unknown")
    
    entry = {
        "PartitionKey": device_ip.replace(".", "_"),
        "RowKey": f"{int(now.timestamp()):010d}_{uuid.uuid4().hex[:8]}",
        "deviceIp": device_ip,
        "deviceId": payload.get("deviceId"),
        "commandStatus": payload.get("commandStatus"),
        "timestamp": timestamp,
        # Date breakdown fields for easier table inspection
        "year": now.year,
        "month": now.month,
        "day": now.day,
        "hour": now.hour,
        "humidity": payload.get("humidity"),
        "temperature": payload.get("temperature"),
        "battery": payload.get("battery"),
        "moisture": payload.get("moisture"),
        "ph": payload.get("ph"),
        "light": payload.get("light"),
    }
    
    client = get_table_client("SensorData")
    if client:
        try:
            client.create_entity(entity=entry)
        except Exception as e:
            logging.error("Failed to save sensor entry to Table Storage: %s", e)

    # Also update/ensure device entry exists (propagate lastSeen if device supplied timestamp)
    try:
        persist_device(
            payload.get("deviceId", "unknown"),
            device_ip,
            payload.get("port", 80),
            payload.get("deviceType", "soil_sensor"),
            last_seen=timestamp
        )
    except Exception as e:
        logging.error(f"Failed to auto-persist device: {e}")

    try:
        update_rollups(entry)
    except Exception as e:
        logging.error(f"Failed to update history rollups: {e}")
        
    logging.info("Sensor data recorded for %s (device_ts_provided=%s)", device_ip, bool(parsed_dt))
    return entry


def fetch_latest_sensor_entry(device_ip: Optional[str] = None, device_id: Optional[str] = None) -> Optional[dict]:
    client = get_table_client("SensorData")
    if not client:
        return None

    query = ""
    if device_ip:
        query = f"PartitionKey eq '{device_ip.replace('.', '_')}'"
    
    # Tables don't support easy "latest" across all partitions.
    # We restrict the search to recent data (last hour) to avoid massive table scans.
    now = datetime.datetime.now(datetime.timezone.utc)
    since = now - datetime.timedelta(hours=1)
    time_filter = f"RowKey ge '{int(since.timestamp()):010d}_0'"
    
    query = f"({query}) and {time_filter}" if query else time_filter

    try:
        # Get entities and sort them to find the true latest
        entities = list(client.query_entities(query_filter=query))
    except Exception as e:
        logging.error(f"Table query error: {e}")
        return None
        
    if not entities:
        # Fall back to a wider search if no data in the last hour
        since_24h = now - datetime.timedelta(hours=24)
        query_24h = f"RowKey ge '{int(since_24h.timestamp()):010d}_0'"
        if device_ip:
            query_24h = f"PartitionKey eq '{device_ip.replace('.', '_')}' and {query_24h}"
        try:
            entities = list(client.query_entities(query_filter=query_24h))
        except:
            return None

    if not entities:
        return None

    # Sort by timestamp string descending
    latest = sorted(entities, key=lambda x: str(x.get("timestamp", "")), reverse=True)[0]

    # Ensure timestamp exists and is an ISO string (fallback to Table's native Timestamp)
    if not latest.get("timestamp"):
        ts_obj = latest.get("Timestamp")
        if isinstance(ts_obj, datetime.datetime):
            latest["timestamp"] = ts_obj.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        elif ts_obj is not None:
            latest["timestamp"] = str(ts_obj)

    # Normalize timestamp string so client JS can parse it reliably
    if latest.get("timestamp"):
        latest["timestamp"] = sanitize_timestamp(latest.get("timestamp"))

    # Get device info
    device_client = get_table_client("Devices")
    target_ip = latest.get("deviceIp")
    device = None
    if device_client and target_ip:
        try:
            device = device_client.get_entity(partition_key="Device", row_key=target_ip.replace(".", "_"))
            # Normalize device lastSeen if present
            try:
                if device.get("lastSeen"):
                    device["lastSeen"] = sanitize_timestamp(device.get("lastSeen"))
            except Exception:
                pass
        except:
            pass

    return {**dict(latest), "device": dict(device) if device else None}


def get_history_target_points(timescale: str, row_count: Optional[int] = None) -> Optional[int]:
    if timescale == "1h":
        return None
    if timescale == "1d":
        return 24
    if timescale == "1m":
        return 720
    if timescale == "1y":
        return 365
    if timescale == "all":
        return 365
    return 60


def parse_timestamp(value) -> Optional[datetime.datetime]:
    if not value:
        return None
    try:
        normalized = str(value)
        if normalized.endswith("+00:00Z"):
            normalized = normalized.replace("+00:00Z", "Z")
        return datetime.datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except Exception:
        return None


def select_evenly_spaced_rows(rows: list, limit: Optional[int]) -> list:
    if not limit or limit <= 0 or len(rows) <= limit:
        return rows

    step = len(rows) / float(limit)
    selected = []
    last_index = -1

    for i in range(limit):
        index = math.ceil((i + 1) * step) - 1
        if index <= last_index:
            index = last_index + 1
        if index >= len(rows):
            index = len(rows) - 1
        selected.append(rows[index])
        last_index = index

    return selected


def downsample_rows_time_window(rows: list, window_start: datetime.datetime, window_end: datetime.datetime, target_points: int) -> list:
    if not target_points or target_points <= 0:
        return rows
    if not window_start or not window_end:
        return rows
    if window_end <= window_start:
        return rows

    window_seconds = max(1, int((window_end - window_start).total_seconds()))
    bucket_seconds = max(1, int(math.ceil(window_seconds / float(target_points))))

    buckets: Dict[int, Dict[str, Any]] = {}

    for row in rows:
        timestamp = row.get("timestamp")
        if not timestamp:
            continue
        parsed_dt = parse_timestamp(timestamp)
        if not parsed_dt:
            continue
        if parsed_dt < window_start or parsed_dt > window_end:
            continue

        bucket_index = int((parsed_dt - window_start).total_seconds()) // bucket_seconds
        bucket = buckets.get(bucket_index)
        if not bucket:
            bucket = {
                "timestamps": [],
                "humidity": [],
                "temperature": [],
                "battery": [],
                "moisture": [],
                "ph": [],
                "light": [],
                "deviceIp": row.get("deviceIp"),
            }
            buckets[bucket_index] = bucket

        bucket["timestamps"].append(parsed_dt)
        bucket["humidity"].append(row.get("humidity"))
        bucket["temperature"].append(row.get("temperature"))
        bucket["battery"].append(row.get("battery"))
        bucket["moisture"].append(row.get("moisture"))
        bucket["ph"].append(row.get("ph"))
        bucket["light"].append(row.get("light"))

    if not buckets:
        return []

    def avg(values):
        numeric = [v for v in values if isinstance(v, (int, float))]
        return round(sum(numeric) / len(numeric), 2) if numeric else None

    aggregated = []
    for idx in sorted(buckets.keys()):
        bucket = buckets[idx]
        bucket_end = max(bucket["timestamps"]) if bucket.get("timestamps") else None
        if not bucket_end:
            continue
        aggregated.append({
            "timestamp": bucket_end.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "humidity": avg(bucket["humidity"]),
            "temperature": avg(bucket["temperature"]),
            "battery": avg(bucket["battery"]),
            "moisture": avg(bucket["moisture"]),
            "ph": avg(bucket["ph"]),
            "light": avg(bucket["light"]),
            "deviceIp": bucket.get("deviceIp"),
            "isAggregated": True,
        })

    return aggregated


def fill_time_buckets(rows: list, window_start: datetime.datetime, window_end: datetime.datetime, target_points: int) -> list:
    if not target_points or target_points <= 0:
        return rows
    if not window_start or not window_end or window_end <= window_start:
        return rows

    window_seconds = max(1, int((window_end - window_start).total_seconds()))
    bucket_seconds = max(1, int(math.ceil(window_seconds / float(target_points))))

    buckets: list[Optional[dict]] = [None] * target_points
    for row in rows:
        timestamp = row.get("timestamp")
        if not timestamp:
            continue
        parsed_dt = parse_timestamp(timestamp)
        if not parsed_dt:
            continue
        if parsed_dt < window_start or parsed_dt > window_end:
            continue
        bucket_index = int((parsed_dt - window_start).total_seconds()) // bucket_seconds
        if bucket_index < 0 or bucket_index >= target_points:
            continue

        existing = buckets[bucket_index]
        if not existing:
            buckets[bucket_index] = row
            continue
        existing_ts = parse_timestamp(existing.get("timestamp"))
        if not existing_ts or parsed_dt >= existing_ts:
            buckets[bucket_index] = row

    device_ip = None
    for row in rows:
        if row.get("deviceIp"):
            device_ip = row.get("deviceIp")
            break

    output = []
    for idx in range(target_points):
        bucket_end = window_start + datetime.timedelta(seconds=bucket_seconds * (idx + 1))
        if bucket_end > window_end:
            bucket_end = window_end
        row = buckets[idx]
        if row:
            output.append(row)
            continue
        output.append({
            "timestamp": bucket_end.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "humidity": None,
            "temperature": None,
            "battery": None,
            "moisture": None,
            "ph": None,
            "light": None,
            "deviceIp": device_ip,
            "isAggregated": True,
            "isGap": True,
        })

    return output


def rebuild_rollups_for_window(window_hours: int = 48, max_rows: int = 50000) -> dict:
    """Rebuild recent rollup buckets from raw SensorData in an idempotent way."""
    source_client = get_table_client("SensorData")
    rollup_client = get_rollup_table_client()
    if not source_client or not rollup_client:
        return {"processedRows": 0, "writtenRollups": 0, "error": "storage unavailable"}

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=window_hours)
    query = f"RowKey ge '{int(since.timestamp()):010d}_0'"

    try:
        entities = list(source_client.query_entities(
            query_filter=query,
            select=["PartitionKey", "RowKey", "timestamp", "deviceIp", "humidity", "temperature", "battery", "moisture", "ph", "light", "Timestamp"],
        ))
    except Exception as ex:
        logging.error("Rollup reconcile query failed: %s", ex)
        return {"processedRows": 0, "writtenRollups": 0, "error": str(ex)}

    if max_rows and len(entities) > max_rows:
        entities = entities[-max_rows:]

    buckets: Dict[tuple[str, str, str], Dict[str, Any]] = {}

    for entity in entities:
        row = dict(entity)
        ts = parse_timestamp(row.get("timestamp") or row.get("Timestamp"))
        if not ts:
            continue

        device_ip = row.get("deviceIp") or str(row.get("PartitionKey", "unknown")).replace("_", ".")

        for granularity in ("hour", "day", "month"):
            bucket_start = floor_to_bucket(ts, granularity)
            bucket_key = (device_ip, granularity, rollup_row_key(bucket_start))
            bucket = buckets.get(bucket_key)
            if not bucket:
                bucket = {
                    "deviceIp": device_ip,
                    "granularity": granularity,
                    "bucket_start": bucket_start,
                    "count": 0,
                    "sums": {"humidity": 0.0, "temperature": 0.0, "battery": 0.0, "moisture": 0.0, "ph": 0.0, "light": 0.0},
                    "numericCounts": {"humidity": 0, "temperature": 0, "battery": 0, "moisture": 0, "ph": 0, "light": 0},
                }
                buckets[bucket_key] = bucket

            bucket["count"] += 1
            for field in ("humidity", "temperature", "battery", "moisture", "ph", "light"):
                value = row.get(field)
                if value is None:
                    continue
                try:
                    numeric = float(value)
                except Exception:
                    continue
                bucket["sums"][field] += numeric
                bucket["numericCounts"][field] += 1

    written = 0
    for bucket in buckets.values():
        bucket_start = bucket["bucket_start"]
        sums = bucket["sums"]
        numeric_counts = bucket["numericCounts"]

        def bucket_avg(field: str) -> Optional[float]:
            cnt = numeric_counts.get(field, 0)
            if not cnt:
                return None
            return round(sums.get(field, 0.0) / cnt, 2)

        entity = {
            "PartitionKey": rollup_bucket_key(bucket["deviceIp"], bucket["granularity"]),
            "RowKey": rollup_row_key(bucket_start),
            "deviceIp": bucket["deviceIp"],
            "granularity": bucket["granularity"],
            "timestamp": rollup_row_key(bucket_start),
            "count": bucket["count"],
            "humidity": bucket_avg("humidity"),
            "temperature": bucket_avg("temperature"),
            "battery": bucket_avg("battery"),
            "moisture": bucket_avg("moisture"),
            "ph": bucket_avg("ph"),
            "light": bucket_avg("light"),
            "lastUpdated": now_iso(),
        }

        try:
            rollup_client.upsert_entity(mode=UpdateMode.REPLACE, entity=entity)
            written += 1
        except Exception as ex:
            logging.warning("Rollup reconcile upsert failed for %s/%s: %s", entity.get("PartitionKey"), entity.get("RowKey"), ex)

    return {"processedRows": len(entities), "writtenRollups": written}


def fetch_rollup_history(device_ip: Optional[str], timescale: str, start_timestamp: Optional[str], end_timestamp: Optional[str], limit: Optional[int], allow_all_devices: bool = False) -> list:
    # Try preferred granularity, then fall back to coarser granularities if no rows found.
    granularities = get_rollup_granularities(timescale)
    if not granularities:
        return []

    client = get_rollup_table_client()
    if not client:
        return []

    # Attempt cache lookup for common non-timeboxed rollup reads
    cache_key = (device_ip, timescale, start_timestamp or '', end_timestamp or '', limit or 0)
    cached = _ROLLUP_CACHE.get(cache_key)
    if cached:
        ts, rows = cached
        if time() - ts < _ROLLUP_CACHE_TTL:
            logging.debug("Serving rollup history from cache for %s (age=%.1fs)", cache_key, time() - ts)
            return rows
        else:
            try:
                del _ROLLUP_CACHE[cache_key]
            except Exception:
                pass

    # If no device filter provided, try to resolve latest active device to avoid cross-partition scans
    if not device_ip and not allow_all_devices:
        try:
            latest = fetch_latest_sensor_entry()
            resolved_ip = latest.get("deviceIp") if latest else None
            if resolved_ip:
                device_ip = str(resolved_ip)
                logging.debug("Resolved rollup device_ip to latest active device: %s", device_ip)
        except Exception as ex:
            logging.debug("Unable to resolve default rollup device_ip: %s", ex)

    now = datetime.datetime.now(datetime.timezone.utc)
    since = parse_timestamp(start_timestamp)
    until = parse_timestamp(end_timestamp)

    if not since:
        if timescale == "1d":
            since = now - datetime.timedelta(days=1)
        elif timescale == "1m":
            since = now - datetime.timedelta(days=30)
        elif timescale == "1y":
            since = now - datetime.timedelta(days=365)
        elif timescale == "all":
            since = now - datetime.timedelta(days=3650)

    if not until:
        until = now

    for granularity in granularities:
        start_t = datetime.datetime.now(datetime.timezone.utc)
        filters = []
        if device_ip and not allow_all_devices:
            filters.append(f"PartitionKey eq '{rollup_bucket_key(device_ip, granularity)}'")
        if since:
            filters.append(f"RowKey ge '{rollup_row_key(floor_to_bucket(since, granularity))}'")
        if until:
            filters.append(f"RowKey le '{rollup_row_key(floor_to_bucket(until, granularity))}'")

        query = " and ".join(filters) if filters else ""

        try:
            q_start = datetime.datetime.now(datetime.timezone.utc)
            entities = list(client.query_entities(
                query_filter=query,
                select=["PartitionKey", "RowKey", "timestamp", "deviceIp", "count", "humidity", "temperature", "battery", "moisture", "ph", "light", "granularity", "lastUpdated"]
            ))
            q_elapsed = (datetime.datetime.now(datetime.timezone.utc) - q_start).total_seconds()
            logging.debug(f"Rollup query executed (granularity={granularity}) in {q_elapsed:.3f}s, returned {len(entities)} raw entities")
        except Exception as e:
            logging.error(f"Rollup query error for granularity {granularity}: {e}")
            continue

        proc_start = datetime.datetime.now(datetime.timezone.utc)
        rows = sorted([dict(e) for e in entities], key=lambda x: str(x.get("timestamp", "")))
        proc_elapsed = (datetime.datetime.now(datetime.timezone.utc) - proc_start).total_seconds()
        elapsed = (datetime.datetime.now(datetime.timezone.utc) - start_t).total_seconds()
        logging.debug("Rollup query granularity=%s returned %s rows (proc=%ss total=%ss)", granularity, len(rows), proc_elapsed, elapsed)
        if not rows:
            # Try next (coarser) granularity
            logging.debug("No rollup rows found for granularity %s, trying coarser if available", granularity)
            continue

        for row in rows:
            row["isAggregated"] = True
        target_points = get_history_target_points(timescale, len(rows))
        effective_limit = limit if limit is not None else target_points
        if timescale in ("1d", "1m", "1y", "all") and since and until and effective_limit:
            # Fill missing buckets to keep chart point counts consistent without raw data.
            rows = fill_time_buckets(rows, since, until, effective_limit)
        elif effective_limit and len(rows) > effective_limit:
            # Downsample evenly across the full window to avoid aliasing and preserve coverage.
            rows = select_evenly_spaced_rows(rows, effective_limit)
        _ROLLUP_CACHE[cache_key] = (time(), rows)
        return rows

    return []


def aggregate_history_rows(raw_history: list, timescale: str) -> list:
    target_points = get_history_target_points(timescale)
    if not target_points or len(raw_history) <= target_points:
        return raw_history

    parsed_rows = []
    for row in raw_history:
        timestamp = row.get("timestamp")
        if not timestamp:
            continue
        try:
            parsed_dt = datetime.datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except Exception:
            continue
        parsed_rows.append((parsed_dt, row))

    if len(parsed_rows) <= target_points:
        return raw_history

    parsed_rows.sort(key=lambda item: item[0])
    span_seconds = max(1, int((parsed_rows[-1][0] - parsed_rows[0][0]).total_seconds()))
    bucket_seconds = max(1, (span_seconds + target_points - 1) // target_points)

    buckets = []
    current_bucket_key = None
    current_bucket: Dict[str, Any] = {}

    def avg(values):
        numeric = [v for v in values if isinstance(v, (int, float))]
        return round(sum(numeric) / len(numeric), 2) if numeric else None

    for parsed_dt, row in parsed_rows:
        bucket_key = int(parsed_dt.timestamp()) // bucket_seconds
        if current_bucket_key != bucket_key:
            if current_bucket.get("timestamps"):
                buckets.append(current_bucket)
            current_bucket_key = bucket_key
            current_bucket = {
                "timestamps": [],
                "humidity": [],
                "temperature": [],
                "battery": [],
                "moisture": [],
                "ph": [],
                "light": [],
                "deviceIp": row.get("deviceIp"),
            }

        current_bucket["timestamps"].append(parsed_dt)
        current_bucket["humidity"].append(row.get("humidity"))
        current_bucket["temperature"].append(row.get("temperature"))
        current_bucket["battery"].append(row.get("battery"))
        current_bucket["moisture"].append(row.get("moisture"))
        current_bucket["ph"].append(row.get("ph"))
        current_bucket["light"].append(row.get("light"))

    if current_bucket.get("timestamps"):
        buckets.append(current_bucket)

    aggregated = []
    for bucket in buckets:
        bucket_end = max(bucket["timestamps"])
        aggregated.append({
            "timestamp": bucket_end.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "humidity": avg(bucket["humidity"]),
            "temperature": avg(bucket["temperature"]),
            "battery": avg(bucket["battery"]),
            "moisture": avg(bucket["moisture"]),
            "ph": avg(bucket["ph"]),
            "light": avg(bucket["light"]),
            "deviceIp": bucket.get("deviceIp"),
            "isAggregated": True,
        })

    return aggregated


def fetch_sensor_history(device_ip: Optional[str] = None, timescale: str = "1h", limit: Optional[int] = 100, raw: bool = False, start_timestamp: Optional[str] = None, end_timestamp: Optional[str] = None, allow_all_devices: bool = False) -> list:
    client = get_table_client("SensorData")
    if not client:
        return []

    # When no device filter is provided, pin history reads to the latest active device
    # so table queries remain partition-targeted instead of cross-partition scans.
    if not device_ip and not allow_all_devices:
        try:
            latest = fetch_latest_sensor_entry()
            resolved_ip = latest.get("deviceIp") if latest else None
            if resolved_ip:
                device_ip = str(resolved_ip)
                logging.debug("Resolved history device_ip to latest active device: %s", device_ip)
        except Exception as ex:
            logging.debug("Unable to resolve default history device_ip: %s", ex)

    filters = []
    if device_ip and not allow_all_devices:
        filters.append(f"PartitionKey eq '{device_ip.replace('.', '_')}'")
    used_rowkey_filter = False
    
    # Time window filtering
    now = datetime.datetime.now(datetime.timezone.utc)
    since = None
    until = None
    
    # If custom start/end timestamps provided, use them
    if start_timestamp:
        try:
            since = datetime.datetime.fromisoformat(start_timestamp.replace("Z", "+00:00"))
        except Exception:
            logging.warning(f"Failed to parse start_timestamp: {start_timestamp}")
    
    if end_timestamp:
        try:
            until = datetime.datetime.fromisoformat(end_timestamp.replace("Z", "+00:00"))
        except Exception:
            logging.warning(f"Failed to parse end_timestamp: {end_timestamp}")
    
    # If no custom timestamps, use timescale-based filtering
    if not since:
        if timescale == "1h": since = now - datetime.timedelta(hours=1)
        elif timescale == "1d": since = now - datetime.timedelta(days=1)
        elif timescale == "1m": since = now - datetime.timedelta(days=30)
        elif timescale == "1y": since = now - datetime.timedelta(days=365)
        # "all" has no time filter

    if since:
        filters.append(f"RowKey ge '{int(since.timestamp()):010d}_0'")
        used_rowkey_filter = True

    query = " and ".join(filters) if filters else ""
        
    # Long-range views should prefer the rollup table and avoid the raw SensorData scan.
    if not raw and get_rollup_granularity(timescale):
        t0 = datetime.datetime.now(datetime.timezone.utc)
        rollup_history = fetch_rollup_history(device_ip, timescale, start_timestamp, end_timestamp, limit, allow_all_devices=allow_all_devices)
        t_rollup = (datetime.datetime.now(datetime.timezone.utc) - t0).total_seconds()
        if rollup_history:
            logging.debug(f"Returning {len(rollup_history)} rollup data points for timescale={timescale} (rollup_fetch={t_rollup}s)")
            return rollup_history
        else:
            logging.debug(f"No rollups available for timescale={timescale} (checked {get_rollup_granularities(timescale)}); falling back to raw query")

    try:
        entities = list(client.query_entities(
            query_filter=query,
            select=["PartitionKey", "RowKey", "timestamp", "deviceIp", "humidity", "temperature", "battery", "moisture", "ph", "light", "Timestamp"]
        ))
    except Exception as e:
        logging.error(f"Table query error: {e}")
        return []

    # Sort chronological
    raw_history = sorted([dict(e) for e in entities], key=lambda x: str(x.get("timestamp", "")))

    # Ensure every entry has a timestamp string (fallback to Table's Timestamp value when present)
    for r in raw_history:
        if not r.get("timestamp"):
            ts_obj = r.get("Timestamp")
            if isinstance(ts_obj, datetime.datetime):
                r["timestamp"] = ts_obj.replace(microsecond=0).isoformat().replace("+00:00", "Z")
            elif ts_obj is not None:
                r["timestamp"] = str(ts_obj)
        # Normalize timestamp formats to be parseable by the browser
        if r.get("timestamp"):
            r["timestamp"] = sanitize_timestamp(r.get("timestamp"))

    # Enforce time window based on timestamp field to avoid RowKey/time skew
    if since or until:
        filtered = []
        for r in raw_history:
            ts = parse_timestamp(r.get("timestamp"))
            if not ts:
                continue
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            filtered.append(r)
        raw_history = filtered

    # If raw 1y still starts too late, retry without RowKey filter (timestamp-only window)
    if raw and timescale == "1y" and used_rowkey_filter and since and raw_history:
        min_ts = None
        for r in raw_history:
            ts = parse_timestamp(r.get("timestamp"))
            if ts and (min_ts is None or ts < min_ts):
                min_ts = ts
        if min_ts and min_ts > (since + datetime.timedelta(days=2)):
            try:
                fallback_filters = []
                if device_ip:
                    fallback_filters.append(f"PartitionKey eq '{device_ip.replace('.', '_')}'")
                fallback_query = " and ".join(fallback_filters) if fallback_filters else ""
                fallback_entities = list(client.query_entities(
                    query_filter=fallback_query,
                    select=["PartitionKey", "RowKey", "timestamp", "deviceIp", "humidity", "temperature", "battery", "moisture", "ph", "light", "Timestamp"],
                ))
                fallback_rows = sorted([dict(e) for e in fallback_entities], key=lambda x: str(x.get("timestamp", "")))
                for r in fallback_rows:
                    if not r.get("timestamp"):
                        ts_obj = r.get("Timestamp")
                        if isinstance(ts_obj, datetime.datetime):
                            r["timestamp"] = ts_obj.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                        elif ts_obj is not None:
                            r["timestamp"] = str(ts_obj)
                    if r.get("timestamp"):
                        r["timestamp"] = sanitize_timestamp(r.get("timestamp"))

                filtered = []
                for r in fallback_rows:
                    ts = parse_timestamp(r.get("timestamp"))
                    if not ts:
                        continue
                    if since and ts < since:
                        continue
                    if until and ts > until:
                        continue
                    filtered.append(r)
                raw_history = filtered
            except Exception as ex:
                logging.warning("Raw 1y fallback query failed: %s", ex)

    # If raw flag is set, return unaggregated data (for custom date-range queries)
    if raw:
        logging.debug(f"Returning {len(raw_history)} raw data points (no aggregation)")
        return select_evenly_spaced_rows(raw_history, limit)

    target_points = get_history_target_points(timescale)
    if timescale == "1y" and since and until and target_points:
        aggregated = downsample_rows_time_window(raw_history, since, until, target_points)
        return select_evenly_spaced_rows(aggregated, limit)

    aggregated = aggregate_history_rows(raw_history, timescale)
    return select_evenly_spaced_rows(aggregated, limit)


_control_commands: dict = {} # Keep commands in-memory for now as they are transient

def save_control_command(device_ip: str, command: str, payload: Optional[dict]) -> dict:
    issued_at = now_iso()
    cmd_entry = {
        "deviceIp": device_ip,
        "command": command,
        "payload": payload,
        "issuedAt": issued_at,
    }
    _control_commands[device_ip] = cmd_entry
    return cmd_entry


def fetch_control_command(device_ip: str) -> Optional[dict]:
    return _control_commands.get(device_ip)


def delete_control_command(device_ip: str) -> None:
    if device_ip in _control_commands:
        del _control_commands[device_ip]


@app.function_name("registerDevice")
@app.route(route="devices", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
@safe_function
def register_device(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Device registration request received")

    try:
        payload = req.get_json()
    except ValueError as exc:
        logging.warning("Invalid JSON for device registration: %s", exc)
        return json_response({"error": "Invalid JSON payload"}, status=400)

    ip_address = payload.get("ip") or payload.get("deviceIp")
    port = payload.get("port")
    device_type = payload.get("type", "soil_sensor")

    if not ip_address or not port:
        return json_response({"error": "ip and port are required"}, status=400)

    try:
        port = int(port)
    except (TypeError, ValueError):
        return json_response({"error": "Port must be a number"}, status=400)

    device_id = payload.get("id") or generate_device_id()
    device_info = persist_device(device_id, ip_address, port, device_type)

    return json_response(device_info)


@app.function_name("postSensorData")
@app.route(route="sensor-data", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@safe_function
def save_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Saving sensor data")

    try:
        payload = req.get_json()
    except ValueError as exc:
        logging.warning("Invalid JSON for sensor data: %s", exc)
        return json_response({"error": "Invalid JSON payload"}, status=400)

    device_ip = payload.get("deviceIp")

    if not device_ip:
        return json_response({"error": "Device IP is required"}, status=400)

    entry = store_sensor_entry(payload)
    return json_response({"message": "Sensor data stored", "data": entry}, status=201)


@app.function_name("getSensorData")
@app.route(route="sensor-data", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@safe_function
def get_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")
    device_id = req.params.get("deviceId")
    is_history = parse_bool(req.params.get("history"), False)

    if is_history:
        timescale = req.params.get("timescale", "1h")
        raw = parse_bool(req.params.get("raw"), False)
        start_timestamp = req.params.get("start")
        end_timestamp = req.params.get("end")
        limit_param = req.params.get("limit")
        if limit_param is not None:
            limit = int(limit_param)
        else:
            limit = None
        allow_all_devices = parse_bool(req.params.get("allowAllDevices"), True)
        
        data = fetch_sensor_history(
            device_ip=device_ip,
            timescale=timescale,
            limit=limit,
            raw=raw,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            allow_all_devices=allow_all_devices,
        )
        return json_response({"count": len(data), "history": data, "timescale": timescale})

    entry = fetch_latest_sensor_entry(device_ip=device_ip, device_id=device_id)

    if not entry:
        message = "No data available"
        if device_ip: message += f" for IP {device_ip}"
        if device_id: message += f" for ID {device_id}"
        return json_response({"error": message}, status=404)

    return json_response(entry)


@app.function_name("queueControlCommand")
@app.route(route="control", methods=["POST"], auth_level=func.AuthLevel.FUNCTION)
@safe_function
def queue_control_command(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Control command request")

    try:
        body = req.get_json()
    except ValueError as exc:
        logging.warning("Invalid JSON for control command: %s", exc)
        return json_response({"error": "Invalid JSON payload"}, status=400)

    device_ip = body.get("deviceIp")
    command = body.get("command")

    if not device_ip or not command:
        return json_response({"error": "deviceIp and command are required"}, status=400)

    command_entry = save_control_command(device_ip, command, body.get("payload"))
    return json_response({"message": "Command queued", "command": command_entry})


@app.function_name("getControlCommand")
@app.route(route="control", methods=["GET"], auth_level=func.AuthLevel.FUNCTION)
@safe_function
def get_control_command(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")

    if not device_ip:
        return json_response({"error": "Device IP is required"}, status=400)

    consume = parse_bool(req.params.get("consume"), True)
    command_entry = fetch_control_command(device_ip)

    if command_entry and consume:
        delete_control_command(device_ip)

    payload = command_entry or {"deviceIp": device_ip, "command": None, "status": "idle"}
    return json_response(payload)


@app.function_name("rollupReconcileTimer")
@app.schedule(schedule="0 */15 * * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def rollup_reconcile_timer(timer: func.TimerRequest) -> None:
    enabled = str(os.getenv("ENABLE_ROLLUP_RECONCILE", "true")).strip().lower() in ("1", "true", "yes")
    if not enabled:
        logging.info("Rollup reconcile timer is disabled via ENABLE_ROLLUP_RECONCILE")
        return

    try:
        window_hours = int(os.getenv("ROLLUP_RECONCILE_WINDOW_HOURS", "48"))
    except Exception:
        window_hours = 48

    try:
        max_rows = int(os.getenv("ROLLUP_RECONCILE_MAX_ROWS", "50000"))
    except Exception:
        max_rows = 50000

    start = datetime.datetime.now(datetime.timezone.utc)
    result = rebuild_rollups_for_window(window_hours=window_hours, max_rows=max_rows)
    elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
    logging.info(
        "Rollup reconcile completed in %ss (window_hours=%s, processedRows=%s, writtenRollups=%s, error=%s)",
        round(elapsed, 2),
        window_hours,
        result.get("processedRows"),
        result.get("writtenRollups"),
        result.get("error"),
    )


@app.function_name("rollupDailyBackfillTimer")
@app.schedule(schedule="0 5 2 * * *", arg_name="timer", run_on_startup=False, use_monitor=True)
def rollup_daily_backfill_timer(timer: func.TimerRequest) -> None:
    enabled = str(os.getenv("ENABLE_ROLLUP_DAILY_BACKFILL", "true")).strip().lower() in ("1", "true", "yes")
    if not enabled:
        logging.info("Daily rollup backfill is disabled via ENABLE_ROLLUP_DAILY_BACKFILL")
        return

    try:
        window_days = int(os.getenv("ROLLUP_DAILY_BACKFILL_DAYS", "400"))
    except Exception:
        window_days = 400

    try:
        max_rows = int(os.getenv("ROLLUP_DAILY_BACKFILL_MAX_ROWS", "200000"))
    except Exception:
        max_rows = 200000

    window_hours = max(1, window_days * 24)
    start = datetime.datetime.now(datetime.timezone.utc)
    result = rebuild_rollups_for_window(window_hours=window_hours, max_rows=max_rows)
    elapsed = (datetime.datetime.now(datetime.timezone.utc) - start).total_seconds()
    logging.info(
        "Daily rollup backfill completed in %ss (window_days=%s, processedRows=%s, writtenRollups=%s, error=%s)",
        round(elapsed, 2),
        window_days,
        result.get("processedRows"),
        result.get("writtenRollups"),
        result.get("error"),
    )


@app.function_name("healthCheck")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
@safe_function
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    headers = {
        "Access-Control-Allow-Origin": "https://soil.tybierwagen.com",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    }
    return func.HttpResponse("OK", status_code=200, headers=headers)


@app.function_name("testEmail")
@app.route(route="test-email", methods=["GET","POST"], auth_level=func.AuthLevel.ANONYMOUS)
@safe_function
def test_email(req: func.HttpRequest) -> func.HttpResponse:
    """
    Trigger a test alert email. Query/body params:
    - to: recipient email (overrides ALERT_RECIPIENT env)
    - from: sender email (overrides ACS_SENDER_EMAIL env)
    - deviceId: optional device id shown in subject (default 'test-device')
    """
    logging.info("Test email request received")
    try:
        body = {}
        if req.method == "POST":
            try:
                body = req.get_json()
            except:
                pass

        to = (req.params.get("to") or (body.get("to") if body else None) or os.getenv("ALERT_RECIPIENT") or "tybierwagen@gmail.com")
        sender = (req.params.get("from") or (body.get("from") if body else None) or os.getenv("ACS_SENDER_EMAIL") or "DoNotReply@tybierwagen.com")

        # Temporarily override env vars for this process so send_alert_email picks them up
        if to:
            os.environ["ALERT_RECIPIENT"] = to
        if sender:
            os.environ["ACS_SENDER_EMAIL"] = sender

        # Ensure device_id is a concrete str (avoid passing None/Any to send_alert_email)
        device_id_raw = req.params.get("deviceId") or (body.get("deviceId") if body else None)
        device_id = str(device_id_raw) if device_id_raw is not None else "test-device"

        # Optional lastSeen override (ISO string). If provided, it's used instead of now().
        last_seen_raw = req.params.get("lastSeen") or (body.get("lastSeen") if body else None)
        last_seen = None
        if last_seen_raw:
            last_seen = sanitize_timestamp(last_seen_raw)

        # Optional subject override. If subject == "sender", use the sender email as the subject.
        subject_raw = req.params.get("subject") or (body.get("subject") if body else None)
        subject = None
        if subject_raw:
            subject = str(subject_raw)
            if subject.lower() == "sender":
                subject = sender

        # Debug flag: when true, return ACS exception details in the send_result for diagnostics
        debug = parse_bool(req.params.get("debug"), False)
        if not debug and body:
            debug = parse_bool(body.get("debug"), False)

        # If last_seen isn't provided, default to now
        if not last_seen:
            last_seen = now_iso()

        send_result = send_alert_email(device_id, last_seen, subject, debug=debug)
        return json_response({"message": "Test email attempted", "recipient": to, "sender": sender, "subject": subject, "send_result": send_result})
    except Exception as e:
        logging.error("Failed to send test email: %s", e)
        return json_response({"error":"Failed to send test email", "details": str(e)}, status=500)


def send_alert_email(device_id: str, last_seen: str, subject_override: Optional[str] = None, debug: bool = False) -> dict:
    """Send an alert email. Prefer Azure Communication Services (ACS) if configured, otherwise fall back to SMTP.
    If `subject_override` is provided it will be used as the email subject. Use the special value "sender" to
    set the subject to the verified ACS sender email address.

    When `debug=True`, ACS exceptions (if any) will be returned in the result under the key `acs_exception`.

    Returns a dict describing how the send was attempted and any identifiers or errors.
    Example: { "method": "acs", "id": "<msg-id>" } or { "method": "smtp", "sent": True }
    """
    recipient = os.getenv("ALERT_RECIPIENT", "tybierwagen@tamu.edu")

    # Try Azure Communication Services first (connection string stored in Key Vault for production)
    acs_conn = os.getenv("ACS_CONNECTION_STRING")
    acs_sender = os.getenv("ACS_SENDER_EMAIL", "DoNotReply@tybierwagen.com")

    # Parse last_seen into a timezone-aware datetime (assume input is iso/z)
    try:
        last_seen_dt_utc = datetime.datetime.fromisoformat(str(last_seen).replace("Z", "+00:00"))
    except Exception:
        # Fallback: treat as current time minus 0 seconds
        last_seen_dt_utc = datetime.datetime.now(datetime.timezone.utc)

    now_utc = datetime.datetime.now(datetime.timezone.utc)

    # Convert to Central Time (America/Chicago). ZoneInfo may be unavailable on Python<3.9 in some runtimes.
    if ZoneInfo:
        central_tz = ZoneInfo("America/Chicago")
    else:
        central_tz = datetime.timezone(datetime.timedelta(hours=-5))  # fallback for CST (no DST shift)

    try:
        last_seen_central = last_seen_dt_utc.astimezone(central_tz)
    except Exception:
        last_seen_central = last_seen_dt_utc.replace(tzinfo=datetime.timezone.utc).astimezone(central_tz)
    now_central = now_utc.astimezone(central_tz)

    # Human readable fields
    last_seen_str = last_seen_central.replace(microsecond=0).isoformat()
    now_str = now_central.replace(microsecond=0).isoformat()

    elapsed_seconds = (now_utc - last_seen_dt_utc).total_seconds()
    elapsed_str = format_timedelta(elapsed_seconds)

    body = f"""
    The soil sensor device '{device_id}' has gone offline.

    Last Seen (Central): {last_seen_str}
    Current Time (Central): {now_str}

    Not seen in: {elapsed_str}

    Please check the robot's power and network connection.
    """

    # Determine subject
    if subject_override:
        subject = str(subject_override)
    else:
        subject = f"ALERT: Soil Sensor Offline - {device_id}"

    # If subject was explicitly set to the sentinel "sender", use the configured ACS sender email
    if subject and subject.lower() == "sender":
        subject = acs_sender or os.getenv("ACS_SENDER_EMAIL") or subject

    acs_exception = None

    # Attempt ACS send and return result including message id when available
    if acs_conn and acs_sender:
        try:
            from azure.communication.email import EmailClient
            client = EmailClient.from_connection_string(acs_conn)

            # Use the payload shape expected by ACS SDK (senderAddress and recipient address)
            message = {
                "senderAddress": acs_sender,
                "content": {"subject": subject, "plainText": body},
                "recipients": {"to": [{"address": recipient}]}
            }

            poller = client.begin_send(message) # type: ignore
            resp = poller.result()
            # Response may be a mapping or object; try common keys
            msg_id = None
            try:
                if isinstance(resp, dict):
                    msg_id = resp.get('id') or resp.get('messageId') or resp.get('message_id')
                else:
                    msg_id = getattr(resp, 'id', None)
            except Exception:
                msg_id = None

            logging.info("Alert email queued via ACS to %s (id=%s)", recipient, msg_id)
            result: Dict[str, Any] = {"method": "acs", "id": msg_id}
            if debug:
                result["body_preview"] = body
            return result
        except Exception as e:
            logging.exception("Failed to send alert via ACS, will attempt SMTP fallback: %s", e)
            acs_exception = {"error": str(e), "trace": traceback.format_exc()}

    # Fallback to SMTP if ACS not configured or failed
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        logging.warning("SMTP credentials not configured. Skipping email alert.")
        result: Dict[str, Any] = {"method": "none", "reason": "smtp_credentials_missing"}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body
        return result
    msg = MIMEMultipart()
    msg['From'] = smtp_user or acs_sender
    msg['To'] = recipient
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logging.info("Alert email sent to %s", recipient)
        result: Dict[str, Any] = {"method": "smtp", "sent": True}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body
        return result
    except Exception as e:
        logging.error("Failed to send alert email via SMTP: %s", e)
        result: Dict[str, Any] = {"method": "smtp", "sent": False, "error": str(e)}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body
        return result

@app.function_name("checkDeviceHealth")
@app.timer_trigger(schedule="0 */10 * * * *", arg_name="myTimer", run_on_startup=False, use_monitor=False) 
def check_device_health(myTimer: func.TimerRequest) -> None:
    logging.info("Running scheduled health check")
    client = get_table_client("Devices")
    if not client:
        return

    try:
        # Check all active devices
        devices = list(client.query_entities(query_filter="status eq 'active'"))
        now = datetime.datetime.now(datetime.timezone.utc)
        
        for device in devices:
            last_seen_str = device.get("lastSeen")
            if not last_seen_str:
                continue
            
            try:
                last_seen = datetime.datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
                diff = (now - last_seen).total_seconds()
                
                # If offline for more than 10 minutes (600 seconds)
                if diff > 600:
                    # Check if we've already sent an alert in the last 24 hours to avoid spamming
                    last_alert = device.get("lastAlertSentAt")
                    should_alert = True
                    if last_alert:
                        last_alert_dt = datetime.datetime.fromisoformat(last_alert.replace("Z", "+00:00"))
                        if (now - last_alert_dt).total_seconds() < 86400: # 24 hours
                            should_alert = False
                    
                    if should_alert:
                        device_id = str(device.get("RowKey") or "unknown")
                        logging.warning("Device %s is offline (Last seen: %s). Sending alert.", device_id, last_seen_str)
                        send_alert_email(device_id, last_seen_str)
                        
                        # Update device with alert timestamp
                        device["lastAlertSentAt"] = now_iso()
                        client.update_entity(mode=UpdateMode.REPLACE, entity=device)
                    else:
                        logging.info("Device %s is offline but alert was already sent recently.", device.get("RowKey"))
                else:
                    # Device is back online, reset alert timestamp if needed
                    if device.get("lastAlertSentAt"):
                        logging.info("Device %s is back online. Resetting alert status.", device.get("RowKey"))
                        device["lastAlertSentAt"] = None
                        client.update_entity(mode=UpdateMode.REPLACE, entity=device)
                        
            except Exception as ex:
                logging.error("Error checking health for device %s: %s", device.get("RowKey"), ex)
                
    except Exception as e:
        logging.error("Health check query failed: %s", e)
