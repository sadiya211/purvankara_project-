"""Provider-independent HTTP client.

fetch_* methods do not call the network. No property-data path is known yet.
get() requests a path the caller supplies. It does not choose a provider path.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

from external_data.config import (
    AUTH_BEARER,
    AUTH_NONE,
    CREDENTIALS_NOT_CONFIGURED_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    UNSUPPORTED_AUTH_MESSAGE,
    ExternalAPIConfig,
    load_config,
)

Transport = Callable[[str, dict[str, str], float], tuple[int, bytes]]

_TIMEOUT_DETAIL = "The request timed out."
_CONNECTION_DETAIL = "The connection to the external API failed."
_INVALID_JSON_DETAIL = "The response was not valid JSON."


def _result(
    status: str,
    message: str,
    *,
    reason: str | None = None,
    data: Any = None,
    detail: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "status": status,
        "message": message,
        "data": data,
    }
    if reason is not None:
        body["reason"] = reason
    if detail is not None:
        body["detail"] = detail
    return body


def not_configured_result() -> dict[str, Any]:
    return _result("not_configured", NOT_CONFIGURED_MESSAGE, reason="missing_configuration")


def unavailable_result(reason: str, detail: str | None = None) -> dict[str, Any]:
    return _result("unavailable", UNAVAILABLE_MESSAGE, reason=reason, detail=detail)


def _urllib_transport(url: str, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read() if exc.fp is not None else b""
        return int(exc.code), body


class ExternalRealEstateAPIClient:
    def __init__(
        self,
        config: ExternalAPIConfig | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.config = load_config() if config is None else config
        self._transport = transport or _urllib_transport

    def fetch_projects(self) -> dict[str, Any]:
        return self._fetch_unavailable()

    def fetch_market_data(self) -> dict[str, Any]:
        return self._fetch_unavailable()

    def fetch_pricing(self) -> dict[str, Any]:
        return self._fetch_unavailable()

    def fetch_rental_data(self) -> dict[str, Any]:
        return self._fetch_unavailable()

    def get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        """GET a caller-supplied path under the configured base URL.

        The path and query come from the caller. This method does not select a
        provider endpoint. Failures return a status and a detail, and never
        include the API key, the Authorization header, or the response body.
        """
        if not self.config.base_url:
            return not_configured_result()

        relative = (path or "").strip().lstrip("/")
        if not relative:
            return unavailable_result("provider_adapter_not_registered")

        authorization, auth_error = resolve_authorization(self.config)
        if auth_error is not None:
            return auth_error

        url = self.config.base_url.rstrip("/") + "/" + relative
        query = _query_string(params)
        if query:
            url = url + "?" + query

        headers = {
            "Accept": "application/json",
            "User-Agent": "PuravankaraDSS-ExternalData/1.0",
        }
        if authorization is not None:
            headers["Authorization"] = authorization
        try:
            status, raw = self._transport(url, headers, self.config.timeout_seconds)
        except TimeoutError:
            return unavailable_result("timeout", _TIMEOUT_DETAIL)
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                return unavailable_result("timeout", _TIMEOUT_DETAIL)
            return unavailable_result("connection", _CONNECTION_DETAIL)
        except OSError:
            return unavailable_result("connection", _CONNECTION_DETAIL)

        if status >= 400:
            return unavailable_result("http_error", f"HTTP {status}.")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return unavailable_result("invalid_json", _INVALID_JSON_DETAIL)

        return _result("ok", "", data=payload)

    def _fetch_unavailable(self) -> dict[str, Any]:
        if not self.config.is_configured:
            return not_configured_result()
        return unavailable_result("provider_adapter_not_registered")


def resolve_authorization(config: ExternalAPIConfig) -> tuple[str | None, dict[str, Any] | None]:
    """Choose an Authorization header without treating Bearer as a provider fact.

    When no scheme is configured and a key is present, the header is Bearer.
    That is this client's existing behavior, isolated here until the provider
    documents its own scheme. ``none`` sends no credential. Any other scheme
    is refused and the key is not placed on the request.
    """
    scheme = config.auth_scheme
    if scheme is None:
        if not config.api_key:
            return None, None
        return f"Bearer {config.api_key}", None
    if scheme == AUTH_NONE:
        return None, None
    if scheme == AUTH_BEARER:
        if not config.api_key:
            return None, _result(
                "not_configured",
                CREDENTIALS_NOT_CONFIGURED_MESSAGE,
                reason="missing_credentials",
            )
        return f"Bearer {config.api_key}", None
    return None, _result(
        "unavailable",
        UNSUPPORTED_AUTH_MESSAGE,
        reason="unsupported_auth",
    )


def _query_string(params: dict[str, str] | None) -> str:
    if not params:
        return ""
    pairs: dict[str, str] = {}
    for key, value in params.items():
        if value is None:
            continue
        name = str(key).strip()
        if not name:
            continue
        pairs[name] = str(value)
    if not pairs:
        return ""
    return urllib.parse.urlencode(pairs)
