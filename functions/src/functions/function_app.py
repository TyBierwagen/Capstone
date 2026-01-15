import azure.functions as func
import datetime
import json
import logging
import os
import sqlite3
import uuid
from typing import Optional

app = func.FunctionApp()

DATA_DIR = os.path.join(os.path.dirname(__file__), "storage")
DB_PATH = os.path.join(DATA_DIR, "soil_robot.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                ip TEXT UNIQUE NOT NULL,
                port INTEGER NOT NULL,
                type TEXT,
                registered_at TEXT,
                last_seen TEXT,
                status TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT NOT NULL,
                device_id TEXT,
                command_status TEXT,
                timestamp TEXT NOT NULL,
                moisture REAL,
                temperature REAL,
                humidity REAL,
                ph REAL,
                light INTEGER
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS control_commands (
                device_ip TEXT PRIMARY KEY,
                command TEXT,
                payload TEXT,
                issued_at TEXT
            )
            """
        )
        conn.commit()


def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def json_response(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json")


def parse_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def generate_device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:16]}"


def persist_device(device_id: str, ip_address: str, port: int, device_type: str) -> dict:
    now = now_iso()
    with get_connection() as conn:
        cursor = conn.cursor()
        existing = cursor.execute("SELECT registered_at FROM devices WHERE ip = ?", (ip_address,)).fetchone()
        registered_at = existing["registered_at"] if existing else now
        cursor.execute(
            """
            INSERT OR REPLACE INTO devices (id, ip, port, type, registered_at, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, ip_address, port, device_type, registered_at, now, "active"),
        )
        conn.commit()

    return {
        "id": device_id,
        "ip": ip_address,
        "port": port,
        "type": device_type,
        "registeredAt": registered_at,
        "lastSeen": now,
        "status": "active",
    }


def store_sensor_entry(payload: dict) -> dict:
    timestamp = payload.get("timestamp") or now_iso()
    entry = {
        "deviceIp": payload.get("deviceIp"),
        "deviceId": payload.get("deviceId"),
        "commandStatus": payload.get("commandStatus"),
        "timestamp": timestamp,
        "moisture": payload.get("moisture"),
        "temperature": payload.get("temperature"),
        "humidity": payload.get("humidity"),
        "ph": payload.get("ph"),
        "light": payload.get("light"),
    }

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sensor_data (device_ip, device_id, command_status, timestamp, moisture, temperature, humidity, ph, light)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["deviceIp"],
                entry["deviceId"],
                entry["commandStatus"],
                entry["timestamp"],
                entry["moisture"],
                entry["temperature"],
                entry["humidity"],
                entry["ph"],
                entry["light"],
            ),
        )
        conn.commit()

    logging.info("Sensor data recorded for %s", entry["deviceIp"])
    return entry


def fetch_latest_sensor_entry(device_ip: str) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT
                sd.device_ip,
                sd.device_id,
                sd.command_status,
                sd.timestamp,
                sd.moisture,
                sd.temperature,
                sd.humidity,
                sd.ph,
                sd.light,
                d.id AS deviceId,
                d.type AS deviceType,
                d.status AS deviceStatus,
                d.registered_at,
                d.last_seen
            FROM sensor_data sd
            LEFT JOIN devices d ON sd.device_ip = d.ip
            WHERE sd.device_ip = ?
            ORDER BY sd.timestamp DESC
            LIMIT 1
            """,
            (device_ip,),
        ).fetchone()

    if not row:
        return None

    payload = {
        "deviceIp": row["device_ip"],
        "deviceId": row["device_id"],
        "commandStatus": row["command_status"],
        "timestamp": row["timestamp"],
        "moisture": row["moisture"],
        "temperature": row["temperature"],
        "humidity": row["humidity"],
        "ph": row["ph"],
        "light": row["light"],
        "device": {
            "id": row["deviceId"],
            "type": row["deviceType"],
            "status": row["deviceStatus"],
            "registeredAt": row["registered_at"],
            "lastSeen": row["last_seen"],
        },
    }

    return payload


def save_control_command(device_ip: str, command: str, payload: dict | None) -> dict:
    issued_at = now_iso()
    payload_json = json.dumps(payload) if payload is not None else None

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO control_commands (device_ip, command, payload, issued_at)
            VALUES (?, ?, ?, ?)
            """,
            (device_ip, command, payload_json, issued_at),
        )
        conn.commit()

    return {
        "deviceIp": device_ip,
        "command": command,
        "payload": payload,
        "issuedAt": issued_at,
    }


def fetch_control_command(device_ip: str) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT device_ip, command, payload, issued_at
            FROM control_commands
            WHERE device_ip = ?
            """,
            (device_ip,),
        ).fetchone()

    if not row:
        return None

    entry = {
        "deviceIp": row["device_ip"],
        "command": row["command"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
        "issuedAt": row["issued_at"],
    }

    return entry


def delete_control_command(device_ip: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM control_commands WHERE device_ip = ?", (device_ip,))
        conn.commit()


@app.route(route="devices", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="sensor-data", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="sensor-data", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")

    if not device_ip:
        return json_response({"error": "Device IP is required"}, status=400)

    entry = fetch_latest_sensor_entry(device_ip)

    if not entry:
        return json_response({"error": "No data available for this device"}, status=404)

    return json_response(entry)


@app.route(route="control", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="control", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)


init_db()import azure.functions as func
import datetime
import json
import logging
import os
import sqlite3
import uuid
from typing import Optional

app = func.FunctionApp()

DATA_DIR = os.path.join(os.path.dirname(__file__), "storage")
DB_PATH = os.path.join(DATA_DIR, "soil_robot.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id TEXT PRIMARY KEY,
                ip TEXT UNIQUE NOT NULL,
                port INTEGER NOT NULL,
                type TEXT,
                registered_at TEXT,
                last_seen TEXT,
                status TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS sensor_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_ip TEXT NOT NULL,
                device_id TEXT,
                command_status TEXT,
                timestamp TEXT NOT NULL,
                moisture REAL,
                temperature REAL,
                ph REAL,
                light INTEGER
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS control_commands (
                device_ip TEXT PRIMARY KEY,
                command TEXT,
                payload TEXT,
                issued_at TEXT
            )
            """
        )
        conn.commit()


def now_iso() -> str:
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def json_response(payload: dict, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status, mimetype="application/json")


def parse_bool(value, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes")


def generate_device_id() -> str:
    return f"dev_{uuid.uuid4().hex[:16]}"


def persist_device(device_id: str, ip_address: str, port: int, device_type: str) -> dict:
    now = now_iso()
    with get_connection() as conn:
        cursor = conn.cursor()
        existing = cursor.execute("SELECT registered_at FROM devices WHERE ip = ?", (ip_address,)).fetchone()
        registered_at = existing["registered_at"] if existing else now
        cursor.execute(
            """
            INSERT OR REPLACE INTO devices (id, ip, port, type, registered_at, last_seen, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, ip_address, port, device_type, registered_at, now, "active"),
        )
        conn.commit()

    return {
        "id": device_id,
        "ip": ip_address,
        "port": port,
        "type": device_type,
        "registeredAt": registered_at,
        "lastSeen": now,
        "status": "active",
    }


def store_sensor_entry(payload: dict) -> dict:
    timestamp = payload.get("timestamp") or now_iso()
    entry = {
        "deviceIp": payload.get("deviceIp"),
        "deviceId": payload.get("deviceId"),
        "commandStatus": payload.get("commandStatus"),
        "timestamp": timestamp,
        "moisture": payload.get("moisture"),
        "temperature": payload.get("temperature"),
        "ph": payload.get("ph"),
        "light": payload.get("light"),
    }

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sensor_data (device_ip, device_id, command_status, timestamp, moisture, temperature, ph, light)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry["deviceIp"],
                entry["deviceId"],
                entry["commandStatus"],
                entry["timestamp"],
                entry["moisture"],
                entry["temperature"],
                entry["ph"],
                entry["light"],
            ),
        )
        conn.commit()

    logging.info("Sensor data recorded for %s", entry["deviceIp"])
    return entry


def fetch_latest_sensor_entry(device_ip: str) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT
                sd.device_ip,
                sd.device_id,
                sd.command_status,
                sd.timestamp,
                sd.moisture,
                sd.temperature,
                sd.ph,
                sd.light,
                d.id AS deviceId,
                d.type AS deviceType,
                d.status AS deviceStatus,
                d.registered_at,
                d.last_seen
            FROM sensor_data sd
            LEFT JOIN devices d ON sd.device_ip = d.ip
            WHERE sd.device_ip = ?
            ORDER BY sd.timestamp DESC
            LIMIT 1
            """,
            (device_ip,),
        ).fetchone()

    if not row:
        return None

    payload = {
        "deviceIp": row["device_ip"],
        "deviceId": row["device_id"],
        "commandStatus": row["command_status"],
        "timestamp": row["timestamp"],
        "moisture": row["moisture"],
        "temperature": row["temperature"],
        "ph": row["ph"],
        "light": row["light"],
        "device": {
            "id": row["deviceId"],
            "type": row["deviceType"],
            "status": row["deviceStatus"],
            "registeredAt": row["registered_at"],
            "lastSeen": row["last_seen"],
        },
    }

    return payload


def save_control_command(device_ip: str, command: str, payload: dict | None) -> dict:
    issued_at = now_iso()
    payload_json = json.dumps(payload) if payload is not None else None

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO control_commands (device_ip, command, payload, issued_at)
            VALUES (?, ?, ?, ?)
            """,
            (device_ip, command, payload_json, issued_at),
        )
        conn.commit()

    return {
        "deviceIp": device_ip,
        "command": command,
        "payload": payload,
        "issuedAt": issued_at,
    }


def fetch_control_command(device_ip: str) -> Optional[dict]:
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT device_ip, command, payload, issued_at
            FROM control_commands
            WHERE device_ip = ?
            """,
            (device_ip,),
        ).fetchone()

    if not row:
        return None

    entry = {
        "deviceIp": row["device_ip"],
        "command": row["command"],
        "payload": json.loads(row["payload"]) if row["payload"] else None,
        "issuedAt": row["issued_at"],
    }

    return entry


def delete_control_command(device_ip: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM control_commands WHERE device_ip = ?", (device_ip,))
        conn.commit()


@app.route(route="devices", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="sensor-data", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="sensor-data", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")

    if not device_ip:
        return json_response({"error": "Device IP is required"}, status=400)

    entry = fetch_latest_sensor_entry(device_ip)

    if not entry:
        return json_response({"error": "No data available for this device"}, status=404)

    return json_response(entry)


@app.route(route="control", methods=["POST"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="control", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
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


@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)


init_db()
