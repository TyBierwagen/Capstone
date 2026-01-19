import azure.functions as func
import datetime
import json
import logging
import os
import uuid
from typing import Optional
from azure.data.tables import TableServiceClient, UpdateMode

app = func.FunctionApp()

# Storage Configuration
conn_str = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
table_service = TableServiceClient.from_connection_string(conn_str) if conn_str else None

def get_table_client(table_name: str):
    if not table_service:
        return None
    return table_service.get_table_client(table_name)

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
    client = get_table_client("Devices")
    
    # Try to get existing
    existing = None
    if client:
        try:
            existing = client.get_entity(partition_key="Device", row_key=ip_address.replace(".", "_"))
        except:
            pass

    registered_at = existing["registeredAt"] if existing else now
    
    device_info = {
        "PartitionKey": "Device",
        "RowKey": ip_address.replace(".", "_"),
        "id": device_id,
        "ip": ip_address,
        "port": port,
        "type": device_type,
        "registeredAt": registered_at,
        "lastSeen": now,
        "status": "active",
    }
    
    if client:
        client.upsert_entity(mode=UpdateMode.REPLACE, entity=device_info)
    
    return device_info


def store_sensor_entry(payload: dict) -> dict:
    # Use server time consistently for SensorData to ensure reliable charting
    now = datetime.datetime.utcnow()
    timestamp = now.replace(microsecond=0).isoformat() + "Z"
    device_ip = payload.get("deviceIp", "unknown")
    
    entry = {
        "PartitionKey": device_ip.replace(".", "_"),
        "RowKey": f"{now.timestamp()}_{uuid.uuid4().hex[:8]}",
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
        "moisture": payload.get("moisture"),
        "ph": payload.get("ph"),
        "light": payload.get("light"),
    }
    
    client = get_table_client("SensorData")
    if client:
        client.create_entity(entity=entry)
        
    # Also update/ensure device entry exists
    try:
        persist_device(
            payload.get("deviceId", "unknown"),
            device_ip,
            payload.get("port", 80),
            payload.get("deviceType", "soil_sensor")
        )
    except Exception as e:
        logging.error(f"Failed to auto-persist device: {e}")
        
    logging.info("Sensor data recorded for %s", device_ip)
    return entry


def fetch_latest_sensor_entry(device_ip: Optional[str] = None, device_id: Optional[str] = None) -> Optional[dict]:
    client = get_table_client("SensorData")
    if not client:
        return None

    query = ""
    if device_ip:
        query = f"PartitionKey eq '{device_ip.replace('.', '_')}'"
    
    # Tables don't support easy "latest" across all partitions, so we query and sort
    try:
        entities = list(client.query_entities(query_filter=query))
    except Exception as e:
        logging.error(f"Table query error: {e}")
        return None
        
    if not entities:
        return None

    latest = sorted(entities, key=lambda x: str(x.get("timestamp", "")), reverse=True)[0]
    
    # Get device info
    device_client = get_table_client("Devices")
    target_ip = latest.get("deviceIp")
    device = None
    if device_client and target_ip:
        try:
            device = device_client.get_entity(partition_key="Device", row_key=target_ip.replace(".", "_"))
        except:
            pass
    
    return {**dict(latest), "device": dict(device) if device else None}


def fetch_sensor_history(device_ip: Optional[str] = None, timescale: str = "1h", limit: int = 100) -> list:
    client = get_table_client("SensorData")
    if not client:
        return []

    filters = []
    if device_ip:
        filters.append(f"PartitionKey eq '{device_ip.replace('.', '_')}'")
    
    # Time window filtering if timescale is specific
    now = datetime.datetime.utcnow()
    since = None
    if timescale == "1h": since = now - datetime.timedelta(hours=1)
    elif timescale == "1d": since = now - datetime.timedelta(days=1)
    elif timescale == "1m": since = now - datetime.timedelta(days=30)
    elif timescale == "1y": since = now - datetime.timedelta(days=365)

    if since:
        filters.append(f"RowKey ge '{since.timestamp()}_0'")

    query = " and ".join(filters) if filters else ""
        
    try:
        entities = list(client.query_entities(query_filter=query))
    except Exception as e:
        logging.error(f"Table query error: {e}")
        return []
        
    # Sort chronological
    raw_history = sorted([dict(e) for e in entities], key=lambda x: str(x.get("timestamp", "")))
    
    # If we have too many points, aggregate them to ~60 points for the chart
    target_points = 60
    if len(raw_history) <= target_points or timescale == "1h":
        return raw_history[-limit:] if timescale == "all" else raw_history

    # Simple bucket aggregation
    chunk_size = len(raw_history) // target_points
    aggregated = []
    for i in range(0, len(raw_history), chunk_size):
        chunk = raw_history[i:i + chunk_size]
        if not chunk: continue
        
        def avg(key):
            vals = [c[key] for c in chunk if c.get(key) is not None and isinstance(c[key], (int, float))]
            return round(sum(vals) / len(vals), 2) if vals else None

        aggregated.append({
            "timestamp": chunk[-1]["timestamp"],
            "moisture": avg("moisture"),
            "temperature": avg("temperature"),
            "humidity": avg("humidity"),
            "ph": avg("ph"),
            "light": avg("light"),
            "deviceIp": chunk[0].get("deviceIp"),
            "isAggregated": True
        })
    
    return aggregated[:target_points + 5]


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
def get_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")
    device_id = req.params.get("deviceId")
    is_history = parse_bool(req.params.get("history"), False)

    if is_history:
        timescale = req.params.get("timescale", "1h")
        limit = int(req.params.get("limit", 100))
        data = fetch_sensor_history(device_ip=device_ip, timescale=timescale, limit=limit)
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


@app.function_name("healthCheck")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)
