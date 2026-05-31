from azure.data.tables import TableServiceClient
import datetime, time, uuid, os

# Prefer an explicit storage connection string from the environment
# (STORAGE_CONNECTION_STRING or AzureWebJobsStorage). Fall back to
# the emulator for local development when not provided.
CONN = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage") or "UseDevelopmentStorage=true"
svc = TableServiceClient.from_connection_string(CONN)

def ensure_table(name):
    try:
        svc.create_table(name)
    except Exception:
        pass
    return svc.get_table_client(name)

devices_client = ensure_table("Devices")
sensor_client = ensure_table("SensorData")

device_ip = "192.168.1.33"
device_rowkey = device_ip.replace(".", "_")
device_id = "AA:BB:CC:DD:EE:FF"

now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
iso_now = now.isoformat().replace("+00:00", "Z")

# Devices entry
devices_client.upsert_entity({
    "PartitionKey": "Device",
    "RowKey": device_rowkey,
    "id": device_id,
    "ip": device_ip,
    "port": 80,
    "type": "soil_sensor",
    "registeredAt": iso_now,
    "lastSeen": iso_now,
    "status": "active",
    "emailAlertsEnabled": True
})

def add_sensor_row(ts_dt, temp, hum, batt, dev_id=device_id, dev_ip=device_ip):
    ts = ts_dt.replace(microsecond=0)
    epoch10 = f"{int(ts.timestamp()):010d}"
    rowkey = f"{epoch10}_{uuid.uuid4().hex[:8]}"
    entry = {
        "PartitionKey": dev_ip.replace(".", "_"),
        "RowKey": rowkey,
        "deviceIp": dev_ip,
        "deviceId": dev_id,
        "timestamp": ts.isoformat().replace("+00:00", "Z"),
        "year": ts.year,
        "month": ts.month,
        "day": ts.day,
        "hour": ts.hour,
        "humidity": hum,
        "temperature": temp,
        "battery": batt
    }
    sensor_client.create_entity(entry)
    print("Inserted", entry["PartitionKey"], entry["RowKey"])

# Insert sample rows: now, -10min, -1day
add_sensor_row(now, 22.1, 43.5, 3.78)
add_sensor_row(now - datetime.timedelta(minutes=10), 21.9, 44.0, 3.80)
add_sensor_row(now - datetime.timedelta(days=1), 19.5, 48.2, 3.65)