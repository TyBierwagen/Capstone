import azure.functions as func
import datetime
import json
import logging
import os
import uuid
from typing import Optional
from azure.data.tables import TableServiceClient, UpdateMode
from zoneinfo import ZoneInfo

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import traceback

app = func.FunctionApp()

# Storage Configuration
conn_str = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
table_service = TableServiceClient.from_connection_string(conn_str) if conn_str else None

def get_table_client(table_name: str):
    if not table_service:
        return None
    return table_service.get_table_client(table_name)

def now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat() + "Z"


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
    Handles datetime objects and strings like '2026-01-21T17:55:38+00:00Z' or '...+00:00'."""
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        v = value.strip()
        # Normalize common problematic suffixes
        v = v.replace("+00:00Z", "Z").replace("+00:00", "Z")
        return v
    try:
        # Fallback: try parsing to datetime then format to ISO Z
        parsed = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    except Exception:
        return str(value)


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
    now = datetime.datetime.now(datetime.timezone.utc)
    timestamp = now.replace(microsecond=0).isoformat() + "Z"
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


def fetch_sensor_history(device_ip: Optional[str] = None, timescale: str = "1h", limit: int = 100) -> list:
    client = get_table_client("SensorData")
    if not client:
        return []

    filters = []
    if device_ip:
        filters.append(f"PartitionKey eq '{device_ip.replace('.', '_')}'")
    
    # Time window filtering if timescale is specific
    now = datetime.datetime.now(datetime.timezone.utc)
    since = None
    if timescale == "1h": since = now - datetime.timedelta(hours=1)
    elif timescale == "1d": since = now - datetime.timedelta(days=1)
    elif timescale == "1m": since = now - datetime.timedelta(days=30)
    elif timescale == "1y": since = now - datetime.timedelta(days=365)

    if since:
        filters.append(f"RowKey ge '{int(since.timestamp()):010d}_0'")

    query = " and ".join(filters) if filters else ""
        
    try:
        entities = list(client.query_entities(query_filter=query))
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


@app.function_name("testEmail")
@app.route(route="test-email", methods=["GET","POST"], auth_level=func.AuthLevel.ANONYMOUS)
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

    # Convert to Central Time (America/Chicago)
    central_tz = ZoneInfo("America/Chicago")
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
            result = {"method": "acs", "id": msg_id}
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
        result = {"method": "none", "reason": "smtp_credentials_missing"}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logging.info("Alert email sent to %s", recipient)
        result = {"method": "smtp", "sent": True}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body
        return result
    except Exception as e:
        logging.error("Failed to send alert email via SMTP: %s", e)
        result = {"method": "smtp", "sent": False, "error": str(e)}
        if debug and acs_exception:
            result["acs_exception"] = acs_exception
        if debug:
            result["body_preview"] = body

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
