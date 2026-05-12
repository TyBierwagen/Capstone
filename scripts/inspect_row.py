import os
import json
from pathlib import Path
from azure.data.tables import TableServiceClient

# load local.settings.json if present
script_dir = Path(__file__).resolve().parent
settings_path = script_dir / "local.settings.json"
if not settings_path.exists():
    settings_path = script_dir.parent / "functions" / "local.settings.json"
if settings_path.exists():
    try:
        payload = json.loads(settings_path.read_text(encoding="utf-8"))
        for k, v in (payload.get("Values") or {}).items():
            if not os.getenv(k) and isinstance(v, str) and v and not v.startswith("<"):
                os.environ[k] = v
    except Exception:
        pass

conn = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
svc = TableServiceClient.from_connection_string(conn)
client = svc.get_table_client("SensorData")
query = "PartitionKey eq '192_168_1_33'"
for i, e in enumerate(client.query_entities(query_filter=query, select=['PartitionKey','RowKey','timestamp','Timestamp'])):
    print('--- entity', i)
    for k in ['PartitionKey','RowKey','timestamp','Timestamp']:
        print(k, ':', repr(e.get(k)))
    if i >= 4:
        break
