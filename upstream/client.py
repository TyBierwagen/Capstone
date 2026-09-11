"""Small dependency-free client for the Upstream Sensor Storage API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_BASE_URL = "https://vitalapi.pods.portals.tapis.io"


class UpstreamApiError(RuntimeError):
    """Raised when the upstream API returns an error response."""


@dataclass
class LoginResult:
    access_token: str
    token_type: str
    username: str | None = None
    role: str | None = None
    tapis_access_token: str | None = None
    tapis_refresh_token: str | None = None
    tapis_expires_at: int | None = None


class UpstreamClient:
    def __init__(self, base_url: str = DEFAULT_BASE_URL, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.login_result: LoginResult | None = None

    @property
    def access_token(self) -> str | None:
        return self.login_result.access_token if self.login_result else None

    def login(
        self,
        username: str,
        password: str,
        *,
        scope: str = "",
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> LoginResult:
        form: dict[str, str] = {
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": scope,
        }
        if client_id:
            form["client_id"] = client_id
        if client_secret:
            form["client_secret"] = client_secret

        response = self._request(
            "POST",
            "/api/v1/token",
            body=urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            authenticated=False,
        )
        self.login_result = LoginResult(**response)
        return self.login_result

    def request(self, method: str, path: str, payload: Any = None, query: Mapping[str, Any] | None = None) -> Any:
        body = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
        return self._request(method, path, body=body, headers=headers, query=query)

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        query: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        if authenticated and not self.access_token:
            raise UpstreamApiError("Authenticate with client.login() before making this request")

        url = f"{self.base_url}/{path.lstrip('/')}"
        if query:
            encoded_query = urlencode([(key, value) for key, value in query.items() if value is not None], doseq=True)
            if encoded_query:
                url = f"{url}?{encoded_query}"

        request_headers = {"Accept": "application/json", **(headers or {})}
        if authenticated:
            request_headers["Authorization"] = f"{self.login_result.token_type} {self.access_token}"

        request = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw_body = response.read()
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise UpstreamApiError(f"{method.upper()} {path} failed ({error.code}): {details}") from error
        except URLError as error:
            raise UpstreamApiError(f"Unable to reach upstream API: {error.reason}") from error

        if not raw_body:
            return None
        content_type = response.headers.get("Content-Type", "")
        if "json" in content_type:
            return json.loads(raw_body.decode("utf-8"))
        return raw_body.decode("utf-8")