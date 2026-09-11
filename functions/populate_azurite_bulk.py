#!/usr/bin/env python3
"""Bulk-populate Azurite Table storage with realistic SensorData and Devices rows.

Usage:
  python populate_azurite_bulk.py --days 30 --interval 15

The script reads `STORAGE_CONNECTION_STRING` from the environment (falls back to
UseDevelopmentStorage=true). It creates the `Devices` and `SensorData` tables if
they don't exist and inserts synthetic rows for one or more devices.
"""
import argparse
import os
import random
from datetime import datetime, timedelta, timezone
from math import sin, pi

from azure.data.tables import TableServiceClient
from azure.core.exceptions import ResourceExistsError, HttpResponseError


def ip_to_rowkey(ip: str) -> str:
    return ip.replace('.', '_')


def gen_rowkey(ts: datetime) -> str:
    epoch = int(ts.replace(tzinfo=timezone.utc).timestamp())
    return f"{epoch:10d}_{random.getrandbits(32):08x}"


def make_sensor_entity(device_ip: str, device_id: str, ts: datetime) -> dict:
    # natural daily cycle: temperature peaks mid-afternoon, humidity inverse
    hour = ts.hour + ts.minute / 60.0
    day_frac = hour / 24.0
    # temperature: base 18..28C with daily sinusoid
    temp = 20 + 6 * sin(2 * pi * (day_frac - 0.35)) + random.uniform(-0.5, 0.5)
    # humidity: inverse of temp roughly
    hum = 60 - 15 * sin(2 * pi * (day_frac - 0.35)) + random.uniform(-2, 2)
    # battery: tends to charge during daylight (6-18) and deplete at night
    if 6 <= ts.hour < 18:
        batt = 30 + 55 * (0.5 + 0.5 * sin(2 * pi * (day_frac + 0.1))) + random.uniform(-1.5, 1.5)
    else:
        batt = 20 + 40 * (0.5 + 0.5 * sin(2 * pi * (day_frac + 0.1))) + random.uniform(-1.5, 1.5)
    batt = max(0, min(100, batt))
    moisture = max(0, min(100, 40 + 10 * sin(2 * pi * (day_frac - 0.2)) + random.uniform(-3, 3)))
    ph = round(6.5 + 0.5 * sin(2 * pi * (day_frac + 0.25)) + random.uniform(-0.1, 0.1), 2)
    light = max(0, int(800 * max(0, sin(2 * pi * (day_frac - 0.25))) + random.gauss(0, 20)))

    entity = {
        'PartitionKey': ip_to_rowkey(device_ip),
        'RowKey': gen_rowkey(ts),
        'deviceIp': device_ip,
        'deviceId': device_id,
        'timestamp': ts.isoformat(),
        'year': ts.year,
        'month': ts.month,
        'day': ts.day,
        'hour': ts.hour,
        'humidity': round(hum, 2),
        'temperature': round(temp, 2),
        'battery': round(batt, 2),
        'moisture': round(moisture, 2),
        'ph': ph,
        'light': int(light),
    }
    return entity


def ensure_tables(tsc: TableServiceClient, names):
    for n in names:
        try:
            tsc.create_table(n)
            print(f"Created table {n}")
        except ResourceExistsError:
            pass


def insert_bulk(table_client, entities, batch_size=100):
    # naive per-entity insertion; Table transaction batching could be added
    count = 0
    for e in entities:
        try:
            table_client.create_entity(entity=e)
            count += 1
            if count % 200 == 0:
                print(f"Inserted {count} rows so far")
        except HttpResponseError as ex:
            print(f"Failed to insert entity: {ex}")
    return count


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--devices', nargs='+', default=['192.168.1.33','192.168.1.34','192.168.1.35'])
    p.add_argument('--days', type=int, default=30)
    p.add_argument('--interval', type=int, default=15, help='minutes between samples')
    p.add_argument('--start', type=str, default=None, help='start date YYYY-MM-DD (UTC)')
    p.add_argument('--device-prefix', type=str, default='device-', help='deviceId prefix')
    args = p.parse_args()

    conn = os.getenv('STORAGE_CONNECTION_STRING') or os.getenv('AzureWebJobsStorage') or 'UseDevelopmentStorage=true'
    tsc = TableServiceClient.from_connection_string(conn)

    ensure_tables(tsc, ['SensorData', 'Devices'])

    sd_client = tsc.get_table_client('SensorData')
    dev_client = tsc.get_table_client('Devices')

    # create devices entries
    for i, ip in enumerate(args.devices, start=1):
        dev_entity = {
            'PartitionKey': 'Device',
            'RowKey': ip_to_rowkey(ip),
            'ip': ip,
            'deviceId': f"{args.device_prefix}{i}",
            'created': datetime.utcnow().isoformat()
        }
        try:
            dev_client.create_entity(dev_entity)
        except ResourceExistsError:
            pass

    # time range
    if args.start:
        start_dt = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
    else:
        start_dt = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=args.days)
    end_dt = start_dt + timedelta(days=args.days)
    interval = timedelta(minutes=args.interval)

    total_inserted = 0
    for ip in args.devices:
        device_id = f"{args.device_prefix}{args.devices.index(ip)+1}"
        ts = start_dt
        entities = []
        while ts < end_dt:
            e = make_sensor_entity(ip, device_id, ts)
            entities.append(e)
            ts += interval

        print(f"Inserting {len(entities)} rows for {ip} into SensorData")
        inserted = insert_bulk(sd_client, entities)
        total_inserted += inserted

    print(f"Done. Inserted approximately {total_inserted} SensorData rows.")


if __name__ == '__main__':
    main()
