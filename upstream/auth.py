"""Authenticate with Upstream and verify the current identity."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from client import UpstreamApiError, UpstreamClient
from workflows import login_and_verify


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding process environment."""
    if not path.is_file():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#") or "=" not in entry:
            continue
        key, value = entry.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    load_dotenv(Path(__file__).with_name(".env"))
    username = os.getenv("UPSTREAM_USERNAME") or input("Upstream username: ")
    password = os.getenv("UPSTREAM_PASSWORD") or getpass.getpass("Upstream password: ")
    client = UpstreamClient(os.getenv("UPSTREAM_BASE_URL", "https://vitalapi.pods.portals.tapis.io"))

    try:
        identity = login_and_verify(client, username, password)
    except UpstreamApiError as error:
        print(f"Upstream authentication failed: {error}", file=sys.stderr)
        return 1

    print(f"Authenticated as {identity.get('username')} (role: {identity.get('role') or 'unknown'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())