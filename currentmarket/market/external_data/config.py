"""Environment configuration for a future real-estate API.

No provider URL or credential is stored in source. A missing base URL leaves
the framework unconfigured. A missing key does not. Credentials are optional
until the provider's authentication method is known.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

NOT_CONFIGURED_MESSAGE = "External real-estate API is not configured."
UNAVAILABLE_MESSAGE = "External real-estate data unavailable."
PROVIDER_NOT_CONFIGURED_MESSAGE = "External API provider not configured."
CREDENTIALS_NOT_CONFIGURED_MESSAGE = "External API credentials are not configured."
UNSUPPORTED_AUTH_MESSAGE = "External API authentication scheme is not supported."

DEFAULT_TIMEOUT_SECONDS = 15.0
AUTH_BEARER = "bearer"
AUTH_NONE = "none"
SUPPORTED_AUTH_SCHEMES = frozenset({AUTH_BEARER, AUTH_NONE})

_URL_ENV = "EXTERNAL_REAL_ESTATE_API_URL"
_KEY_ENV = "EXTERNAL_REAL_ESTATE_API_KEY"
_TIMEOUT_ENV = "EXTERNAL_REAL_ESTATE_API_TIMEOUT"
_AUTH_ENV = "EXTERNAL_REAL_ESTATE_API_AUTH"


@dataclass(frozen=True)
class ExternalAPIConfig:
    base_url: str | None
    api_key: str | None
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    auth_scheme: str | None = None

    @property
    def is_configured(self) -> bool:
        """A base URL is enough to attempt a caller-supplied path.

        The API key is optional. Authentication is applied only when a scheme
        is selected, or when a key is present and no scheme was set.
        """
        return bool(self.base_url)

    def __repr__(self) -> str:
        key_state = "set" if self.api_key else "missing"
        if self.auth_scheme is None:
            auth_state = "default"
        elif self.auth_scheme in SUPPORTED_AUTH_SCHEMES:
            auth_state = self.auth_scheme
        else:
            auth_state = "unsupported"
        return (
            "ExternalAPIConfig("
            f"base_url={_public_base_url(self.base_url)!r}, "
            f"api_key={key_state}, "
            f"timeout_seconds={self.timeout_seconds}, "
            f"auth_scheme={auth_state})"
        )


def load_config(env: dict[str, str] | None = None) -> ExternalAPIConfig:
    """Read provider settings. The API key is never written to logs from here."""
    source = os.environ if env is None else env
    base_url = _blank_to_none(source.get(_URL_ENV))
    api_key = _blank_to_none(source.get(_KEY_ENV))
    timeout = _parse_timeout(source.get(_TIMEOUT_ENV))
    auth_scheme = _normalize_auth(source.get(_AUTH_ENV))
    return ExternalAPIConfig(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=timeout,
        auth_scheme=auth_scheme,
    )


def _public_base_url(value: str | None) -> str | None:
    """Drop userinfo so a logged config cannot print credentials embedded in the URL."""
    if not value:
        return value
    parts = urlsplit(value)
    if not parts.username and not parts.password:
        return value
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, host, parts.path, "", ""))


def _normalize_auth(value: str | None) -> str | None:
    text = _blank_to_none(value)
    if text is None:
        return None
    return text.casefold()


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_timeout(value: str | None) -> float:
    text = _blank_to_none(value)
    if text is None:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        parsed = float(text)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    if parsed <= 0:
        return DEFAULT_TIMEOUT_SECONDS
    return parsed
