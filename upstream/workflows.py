"""Reusable workflows for moving sensor data through the upstream API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from client import UpstreamClient


def login_and_verify(client: UpstreamClient, username: str, password: str) -> dict[str, Any]:
    client.login(username, password)
    return client.request("GET", "/api/v1/users/me")


def create_campaign(client: UpstreamClient, name: str, **fields: Any) -> int:
    response = client.request("POST", "/api/v1/campaigns", {"name": name, **fields})
    return int(response["id"])


def create_station(client: UpstreamClient, campaign_id: int, name: str, start_date: datetime, timezone: str, **fields: Any) -> int:
    payload = {"name": name, "start_date": start_date.isoformat(), "timezone": timezone, **fields}
    response = client.request("POST", f"/api/v1/campaigns/{campaign_id}/stations", payload)
    return int(response["id"])


def create_sensor(client: UpstreamClient, campaign_id: int, station_id: int, **fields: Any) -> int:
    response = client.request(
        "POST",
        f"/api/v1/campaigns/{campaign_id}/stations/{station_id}/sensors",
        fields,
    )
    return int(response["id"])


def record_measurement(
    client: UpstreamClient,
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    measurement_value: float,
    collection_time: datetime,
    **fields: Any,
) -> int:
    payload = {
        "measurementvalue": measurement_value,
        "collectiontime": collection_time.isoformat(),
        **fields,
    }
    response = client.request(
        "POST",
        f"/api/v1/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}/measurements",
        payload,
    )
    return int(response["id"])


def list_measurements(
    client: UpstreamClient,
    campaign_id: int,
    station_id: int,
    sensor_id: int,
    *,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    page: int = 1,
    limit: int = 1000,
) -> dict[str, Any]:
    query = {
        "start_date": start_date.isoformat() if start_date else None,
        "end_date": end_date.isoformat() if end_date else None,
        "page": page,
        "limit": limit,
    }
    return client.request(
        "GET",
        f"/api/v1/campaigns/{campaign_id}/stations/{station_id}/sensors/{sensor_id}/measurements",
        query=query,
    )


def list_campaigns(client: UpstreamClient, *, page: int = 1, limit: int = 20) -> dict[str, Any]:
    return client.request("GET", "/api/v1/campaigns", query={"page": page, "limit": limit})