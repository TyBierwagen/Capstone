"""Upload historical SensorData rows from Azure Table Storage to Upstream."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import os
import time
import uuid
from io import StringIO
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from azure.data.tables import TableServiceClient


SOURCE_TABLE_NAME = "SensorData"
UPLOAD_LEDGER_TABLE_NAME = "UpstreamUploadLedger"
DEFAULT_BASE_URL = "https://vitalapi.pods.portals.tapis.io"
TARGET_CAMPAIGN_ID = "4"
TARGET_STATION_ID = "3"
DEFAULT_LATITUDE = "30.665742"
DEFAULT_LONGITUDE = "-96.326784"
UPLOAD_SENSOR_FIELDS = {
    "temperature": "Celsius",
    "humidity": "Percentage",
    "battery": "Volts",
}
TRANSIENT_UPLOAD_STATUS_CODES = {502, 503, 504}
UPLOAD_RETRY_COUNT = 4


def load_local_settings() -> None:
    settings_path = Path(__file__).resolve().parent.parent / "functions" / "local.settings.json"
    if not settings_path.exists():
        return
    try:
        values = json.loads(settings_path.read_text(encoding="utf-8")).get("Values", {})
    except (OSError, json.JSONDecodeError) as error:
        logging.warning("Unable to read local.settings.json: %s", error)
        return
    for key, value in values.items():
        if not os.getenv(key) and isinstance(value, str) and value and not value.startswith("<"):
            os.environ[key] = value


def parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("+00:00Z"):
            text = text[:-1]
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = dt.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def row_timestamp(row: dict[str, Any]) -> dt.datetime | None:
    return parse_timestamp(row.get("timestamp") or row.get("Timestamp"))


def parse_float(value: Any, field_name: str, row: dict[str, Any]) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"Row {row.get('RowKey', '<unknown>')} has a non-numeric {field_name}") from error


def get_config() -> dict[str, str]:
    return {
        "storage": os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage", ""),
        "base_url": os.getenv("UPSTREAM_BASE_URL", DEFAULT_BASE_URL).rstrip("/"),
        "username": os.getenv("UPSTREAM_USERNAME", ""),
        "password": os.getenv("UPSTREAM_PASSWORD", ""),
        "campaign_id": TARGET_CAMPAIGN_ID,
        "station_id": TARGET_STATION_ID,
        "latitude": os.getenv("UPSTREAM_LATITUDE", DEFAULT_LATITUDE),
        "longitude": os.getenv("UPSTREAM_LONGITUDE", DEFAULT_LONGITUDE),
    }


def iter_rows(client, device_ip: str | None) -> Iterable[dict[str, Any]]:
    query = ""
    if device_ip:
        partition = device_ip.replace(".", "_").replace("'", "''")
        query = f"PartitionKey eq '{partition}'"
    select = ["PartitionKey", "RowKey", "timestamp", "Timestamp", "deviceIp", "latitude", "longitude", *UPLOAD_SENSOR_FIELDS]
    return client.query_entities(query_filter=query, select=list(dict.fromkeys(select)))


def load_uploaded_keys(service: TableServiceClient) -> set[tuple[str, str]]:
    ledger = service.get_table_client(UPLOAD_LEDGER_TABLE_NAME)
    try:
        ledger.create_table()
    except Exception:
        pass
    return {
        (str(row.get("sourcePartitionKey", "")), str(row.get("sourceRowKey", "")))
        for row in ledger.query_entities(query_filter="", select=["sourcePartitionKey", "sourceRowKey"])
    }


def mark_uploaded(service: TableServiceClient, rows: list[dict[str, Any]]) -> None:
    ledger = service.get_table_client(UPLOAD_LEDGER_TABLE_NAME)
    for row in rows:
        ledger.upsert_entity(entity={
            "PartitionKey": str(row.get("PartitionKey", "unknown")),
            "RowKey": str(row.get("RowKey", "unknown")),
            "sourcePartitionKey": str(row.get("PartitionKey", "")),
            "sourceRowKey": str(row.get("RowKey", "")),
            "uploadedAt": dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        })


def make_csvs(rows: list[dict[str, Any]], config: dict[str, str], sensor_fields: list[str]) -> tuple[str, str]:
    sensors = StringIO(newline="")
    sensor_writer = csv.DictWriter(
        sensors,
        fieldnames=["alias", "variablename", "units", "postprocess", "postprocessscript"],
        lineterminator="\n",
    )
    sensor_writer.writeheader()
    for field in sensor_fields:
        sensor_writer.writerow({
            "alias": field,
            "variablename": field,
            "units": UPLOAD_SENSOR_FIELDS[field],
            "postprocess": "false",
            "postprocessscript": "",
        })

    measurements = StringIO(newline="")
    fields = ["collectiontime", "Lat_deg", "Lon_deg", *sensor_fields]
    measurement_writer = csv.DictWriter(measurements, fieldnames=fields, lineterminator="\n")
    measurement_writer.writeheader()
    for row in rows:
        latitude = row.get("latitude") or row.get("Lat_deg") or config["latitude"]
        longitude = row.get("longitude") or row.get("Lon_deg") or config["longitude"]
        if latitude in (None, "") or longitude in (None, ""):
            raise ValueError("UPSTREAM_LATITUDE and UPSTREAM_LONGITUDE are required")
        latitude = parse_float(latitude, "latitude", row)
        longitude = parse_float(longitude, "longitude", row)
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"Row {row.get('RowKey', '<unknown>')} has coordinates outside valid ranges")
        timestamp = row_timestamp(row)
        if timestamp is None:
            raise ValueError(f"Row {row.get('RowKey', '<unknown>')} has no valid timestamp")
        sensor_values = {
            field: "" if row.get(field) in (None, "") else parse_float(row.get(field), field, row)
            for field in sensor_fields
        }
        measurement_writer.writerow({
            "collectiontime": timestamp.isoformat(),
            "Lat_deg": latitude,
            "Lon_deg": longitude,
            **sensor_values,
        })
    return sensors.getvalue(), measurements.getvalue()


def upload_batch(rows: list[dict[str, Any]], config: dict[str, str], sensor_fields: list[str], token: str, token_type: str) -> None:
    sensors_csv, measurements_csv = make_csvs(rows, config, sensor_fields)
    boundary = f"----AzureUpstream{uuid.uuid4().hex}"

    def file_part(name: str, filename: str, content: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"; filename=\"{filename}\"\r\n"
            "Content-Type: text/csv; charset=utf-8\r\n\r\n"
            f"{content}\r\n"
        ).encode("utf-8")

    body = file_part("upload_file_sensors", "sensors.csv", sensors_csv)
    body += file_part("upload_file_measurements", "measurements.csv", measurements_csv)
    body += f"--{boundary}--\r\n".encode("utf-8")
    request = Request(
        f"{config['base_url']}/api/v1/uploadfile_csv/campaign/{config['campaign_id']}/station/{config['station_id']}/sensor",
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"{token_type} {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
        method="POST",
    )
    for attempt in range(1, UPLOAD_RETRY_COUNT + 1):
        try:
            with urlopen(request, timeout=60) as response:
                response.read()
            return
        except HTTPError as error:
            if error.code not in TRANSIENT_UPLOAD_STATUS_CODES or attempt == UPLOAD_RETRY_COUNT:
                raise
            delay = 2 ** (attempt - 1)
            logging.warning(
                "Upstream returned HTTP %s for a %s-row batch; retrying in %s seconds (attempt %s/%s)",
                error.code,
                len(rows),
                delay,
                attempt + 1,
                UPLOAD_RETRY_COUNT,
            )
            time.sleep(delay)


def login_and_verify(config: dict[str, str]) -> tuple[str, str]:
    request = Request(
        f"{config['base_url']}/api/v1/token",
        data=urlencode({
            "grant_type": "password",
            "username": config["username"],
            "password": config["password"],
            "scope": "",
        }).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        token_response = json.loads(response.read().decode("utf-8"))
    token = token_response.get("access_token")
    token_type = token_response.get("token_type", "Bearer")
    if not token:
        raise RuntimeError("Upstream authentication response did not contain an access token")

    verify_request = Request(
        f"{config['base_url']}/api/v1/users/me",
        headers={"Accept": "application/json", "Authorization": f"{token_type} {token}"},
        method="GET",
    )
    with urlopen(verify_request, timeout=30) as response:
        identity = json.loads(response.read().decode("utf-8"))
    logging.info("Authenticated with Upstream as %s", identity.get("username", config["username"]))
    return token, token_type


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload historical SensorData rows to Upstream.")
    parser.add_argument("--device-ip", help="Only upload rows for this device IP.")
    parser.add_argument("--start", help="Only upload rows at or after this ISO 8601 timestamp.")
    parser.add_argument("--end", help="Only upload rows before or at this ISO 8601 timestamp.")
    parser.add_argument("--limit", type=int, help="Upload at most this many rows.")
    parser.add_argument("--batch-size", type=int, default=500, help="Rows per Upstream request (default: 500).")
    parser.add_argument("--dry-run", action="store_true", help="Read and validate rows without authenticating or uploading.")
    args = parser.parse_args()
    if args.batch_size < 1 or args.limit is not None and args.limit < 1:
        parser.error("--batch-size and --limit must be positive")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    load_local_settings()
    config = get_config()
    if not config["storage"]:
        raise RuntimeError("Set STORAGE_CONNECTION_STRING or AzureWebJobsStorage")
    if not args.dry_run and (not config["username"] or not config["password"]):
        raise RuntimeError("Set UPSTREAM_USERNAME and UPSTREAM_PASSWORD")
    start = parse_timestamp(args.start) if args.start else None
    end = parse_timestamp(args.end) if args.end else None
    if args.start and start is None or args.end and end is None:
        parser.error("--start and --end must be valid ISO 8601 timestamps")

    service = TableServiceClient.from_connection_string(config["storage"])
    uploaded_keys = load_uploaded_keys(service)
    rows = []
    for row in iter_rows(service.get_table_client(SOURCE_TABLE_NAME), args.device_ip):
        source_key = (str(row.get("PartitionKey", "")), str(row.get("RowKey", "")))
        if source_key in uploaded_keys:
            continue
        timestamp = row_timestamp(row)
        if timestamp is None or start and timestamp < start or end and timestamp > end:
            continue
        rows.append(dict(row))
        if args.limit and len(rows) >= args.limit:
            break
    rows.sort(key=lambda row: row_timestamp(row) or dt.datetime.min.replace(tzinfo=dt.timezone.utc))
    sensor_fields = [field for field in UPLOAD_SENSOR_FIELDS if any(row.get(field) is not None for row in rows)]
    if rows and not sensor_fields:
        raise ValueError("Historical rows contain none of the configured UPSTREAM_SENSOR_FIELDS")
    if args.dry_run:
        for offset in range(0, len(rows), args.batch_size):
            make_csvs(rows[offset:offset + args.batch_size], config, sensor_fields)
        logging.info("Dry run validated %s historical rows", len(rows))
        return 0
    if not rows:
        logging.info("No historical rows matched the requested filters")
        return 0
    token, token_type = login_and_verify(config)
    for offset in range(0, len(rows), args.batch_size):
        batch = rows[offset:offset + args.batch_size]
        try:
            upload_batch(batch, config, sensor_fields, token, token_type)
        except (HTTPError, URLError) as error:
            raise RuntimeError(f"Upstream upload failed for rows {offset + 1}-{offset + len(batch)}: {error}") from error
        mark_uploaded(service, batch)
        logging.info("Uploaded rows %s-%s of %s", offset + 1, offset + len(batch), len(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())