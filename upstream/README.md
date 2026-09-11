# Upstream API

These files provide a small Python client and reusable workflows for the Upstream Sensor Storage API documented at:

<https://vitalapi.pods.portals.tapis.io/docs>

## Authentication

The login workflow calls `POST /api/v1/token` with a form-encoded password grant. Credentials are read from the environment or prompted interactively.

```powershell
$env:UPSTREAM_USERNAME = "your-username"
$env:UPSTREAM_PASSWORD = "your-password"
python .\upstream\auth.py
```

The auth command logs in, calls `GET /api/v1/users/me`, and prints only the authenticated identity. Tokens are kept in memory and are not written to disk.

## Available workflows

`workflows.py` contains functions for:

- Login and identity verification
- Creating campaigns, stations, and sensors
- Recording measurements
- Listing campaigns and measurements

The client also supports direct authenticated requests for endpoints that are not yet wrapped by a named workflow.

## API conventions

- JSON endpoints use `Authorization: Bearer <access_token>`.
- Login uses `application/x-www-form-urlencoded`.
- Use ISO 8601 timestamps for campaign, station, and measurement dates.
- The API base URL can be overridden with `UPSTREAM_BASE_URL`.