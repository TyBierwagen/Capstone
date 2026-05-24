"""Merge SensorHistoryRollups across devices into a single "all devices" rollup per timestamp.

Usage:
  python scripts/merge_rollups.py --dry-run
  python scripts/merge_rollups.py --commit
  python scripts/merge_rollups.py --commit --delete-original

The script groups entries by `(granularity, RowKey)` and aggregates numeric columns by summing
and records which devices were merged. It writes merged entries to the `SensorHistoryRollups`
table under PartitionKey `all_devices|<granularity>` when `--commit` is provided.
"""
from pathlib import Path
import os
import json
import argparse
from collections import defaultdict
from azure.data.tables import TableServiceClient, UpdateMode


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


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default="SensorHistoryRollups", help="Table name")
    parser.add_argument("--dry-run", dest="commit", action="store_false", help="Don't write, just show summary")
    parser.add_argument("--commit", dest="commit", action="store_true", help="Write merged entries to table")
    parser.add_argument("--delete-original", action="store_true", help="Delete original device-specific rows after commit")
    args = parser.parse_args()

    load_local_settings()

    conn = os.getenv("STORAGE_CONNECTION_STRING") or os.getenv("AzureWebJobsStorage")
    if not conn:
        print("No STORAGE_CONNECTION_STRING or AzureWebJobsStorage environment variable found.")
        raise SystemExit(1)

    svc = TableServiceClient.from_connection_string(conn)
    tc = svc.get_table_client(args.table)

    # Group entities by (granularity, RowKey)
    groups = {}
    originals = defaultdict(list)

    print("Scanning table... this may take time for large tables")
    for e in tc.query_entities(query_filter="", select=None):
        gran = e.get("granularity") or "unknown"
        row = e.get("RowKey")
        key = (gran, row)
        if key not in groups:
            groups[key] = {
                "count": 0,
                "numeric_sums": defaultdict(float),
                "numeric_counts": defaultdict(int),
                "string_props": {},
                "deviceIps": set(),
                "sample": e,
            }
        g = groups[key]
        g["count"] += 1
        originals[key].append((e.get("PartitionKey"), row))
        # Aggregate properties
        for k, v in e.items():
            if k in ("PartitionKey", "RowKey"):
                continue
            if k == "deviceIp":
                if v:
                    g["deviceIps"].add(v)
                continue
            if is_number(v):
                g["numeric_sums"][k] += float(v)
                g["numeric_counts"][k] += 1
            else:
                # keep first non-empty string value as sample
                if k not in g["string_props"] and v is not None:
                    g["string_props"][k] = v

    print(f"Found {len(groups)} groups to consider")

    # Prepare merged entities
    merged_entities = []
    for (gran, row), g in groups.items():
        merged = {}
        merged["PartitionKey"] = f"all_devices|{gran}"
        merged["RowKey"] = row
        merged["granularity"] = gran
        # include sample timestamp or whatever sample has
        sample = g.get("sample") or {}
        if sample.get("timestamp"):
            merged["timestamp"] = sample.get("timestamp")
        # numeric sums
        for k, s in g["numeric_sums"].items():
            # keep summed value; caller may choose to re-normalize if needed
            merged[k] = s
            # also record how many numeric contributions
            merged[f"_{k}_mergedCount"] = g["numeric_counts"].get(k, 0)
        # string props: copy sample values
        for k, v in g["string_props"].items():
            merged[k] = v
        merged["mergedDeviceCount"] = len(g["deviceIps"])
        if g["deviceIps"]:
            merged["mergedDevices"] = ",".join(sorted(g["deviceIps"]))
        merged_entities.append(((gran, row), merged))

    # Dry-run: show summary
    print("\nSample merged entities (first 5):")
    for (gran, row), m in merged_entities[:5]:
        print(f"  gran={gran} RowKey={row} devices={m.get('mergedDeviceCount')} numeric_fields={len([k for k in m.keys() if k not in ('PartitionKey','RowKey','granularity','timestamp','mergedDevices','mergedDeviceCount')])}")

    print(f"\nTotal groups: {len(merged_entities)} (original rows counted per group in metadata)")

    if not args.commit:
        print("Dry-run complete. Re-run with --commit to write merged entries.")
        return

    # Commit merged entities
    print("Committing merged entities to table...")
    for (gran, row), m in merged_entities:
        try:
            tc.upsert_entity(m, mode=UpdateMode.MERGE)
        except Exception as e:
            print("Failed upsert for", (gran, row), e)

    print("Commit finished.")

    if args.delete_original:
        print("Deleting original device-specific rows...")
        for key, items in originals.items():
            for pk, rk in items:
                try:
                    tc.delete_entity(partition_key=pk, row_key=rk)
                except Exception as e:
                    print("Failed delete for", (pk, rk), e)
        print("Deletion finished.")


if __name__ == "__main__":
    main()
