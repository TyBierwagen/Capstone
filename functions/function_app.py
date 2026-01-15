import azure.functions as func
import datetime
import json
import logging
import uuid
from typing import Optional

app = func.FunctionApp()

# In-memory storage (note: data is lost on cold starts, but works reliably on Azure)
# For persistent storage, use Azure Table Storage, Cosmos DB, or Azure SQL
_devices: dict = {}
_sensor_data: list = []
_control_commands: dict = {}


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
    existing = _devices.get(ip_address)
    registered_at = existing["registeredAt"] if existing else now
    
    device_info = {
        "id": device_id,
        "ip": ip_address,
        "port": port,
        "type": device_type,
        "registeredAt": registered_at,
        "lastSeen": now,
        "status": "active",
    }
    _devices[ip_address] = device_info
    return device_info


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
    _sensor_data.append(entry)
    logging.info("Sensor data recorded for %s", entry["deviceIp"])
    return entry


def fetch_latest_sensor_entry(device_ip: str) -> Optional[dict]:
    # Find the latest entry for this device
    matching = [e for e in _sensor_data if e.get("deviceIp") == device_ip]
    if not matching:
        return None
    
    # Sort by timestamp descending and get the first
    latest = sorted(matching, key=lambda x: x.get("timestamp", ""), reverse=True)[0]
    device = _devices.get(device_ip)
    
    return {
        **latest,
        "device": device if device else None,
    }


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


@app.function_name("getSensorData")
@app.route(route="sensor-data", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def get_sensor_data(req: func.HttpRequest) -> func.HttpResponse:
    device_ip = req.params.get("deviceIp")

    if not device_ip:
        return json_response({"error": "Device IP is required"}, status=400)

    entry = fetch_latest_sensor_entry(device_ip)

    if not entry:
        return json_response({"error": "No data available for this device"}, status=404)

    return json_response(entry)


@app.function_name("queueControlCommand")
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


@app.function_name("getControlCommand")
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


@app.function_name("healthCheck")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health_check(req: func.HttpRequest) -> func.HttpResponse:
    return func.HttpResponse("OK", status_code=200)
