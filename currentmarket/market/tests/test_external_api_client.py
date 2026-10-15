"""Mocked HTTP tests for the reusable external API client. No live requests."""

import json
import urllib.error

from external_data.client import ExternalRealEstateAPIClient
from external_data.config import (
    CREDENTIALS_NOT_CONFIGURED_MESSAGE,
    NOT_CONFIGURED_MESSAGE,
    UNAVAILABLE_MESSAGE,
    UNSUPPORTED_AUTH_MESSAGE,
    ExternalAPIConfig,
    load_config,
)

_SECRET = "local-test-key"
_BASE = "http://127.0.0.1:9"


def _client(config, transport):
    return ExternalRealEstateAPIClient(config, transport=transport)


def _configured(**kwargs):
    values = {"base_url": _BASE, "api_key": _SECRET, "timeout_seconds": 1}
    values.update(kwargs)
    return ExternalAPIConfig(**values)


def _assert_secret_hidden(result, captured=None):
    dumped = json.dumps(result)
    assert _SECRET not in dumped
    assert "Authorization" not in dumped
    assert "Bearer" not in dumped
    if captured is not None:
        assert _SECRET not in json.dumps(result)


def test_successful_json_uses_caller_path_and_default_bearer():
    seen = {}

    def transport(url, headers, timeout):
        seen["url"] = url
        seen["headers"] = dict(headers)
        seen["timeout"] = timeout
        return 200, b'{"records":[{"name":"Sample"}]}'

    result = _client(_configured(), transport).get("caller/supplied")
    assert result["status"] == "ok"
    assert result["data"] == {"records": [{"name": "Sample"}]}
    assert seen["url"] == "http://127.0.0.1:9/caller/supplied"
    assert seen["headers"]["Authorization"] == "Bearer local-test-key"
    assert seen["headers"]["Accept"] == "application/json"
    assert seen["timeout"] == 1
    _assert_secret_hidden(result)


def test_query_parameters_are_encoded_and_credentials_stay_off_the_url():
    seen = {}

    def transport(url, headers, timeout):
        seen["url"] = url
        seen["headers"] = dict(headers)
        return 200, b'{"ok":true}'

    result = _client(_configured(auth_scheme="none"), transport).get(
        "caller/supplied",
        params={"city": "Bengaluru", "empty": None, "q": "a b"},
    )
    assert result["status"] == "ok"
    assert result["data"] == {"ok": True}
    assert seen["url"].startswith("http://127.0.0.1:9/caller/supplied?")
    assert "city=Bengaluru" in seen["url"]
    assert "q=a+b" in seen["url"]
    assert "empty" not in seen["url"]
    assert _SECRET not in seen["url"]
    assert "Authorization" not in seen["headers"]
    _assert_secret_hidden(result)


def test_missing_base_url_does_not_call_transport():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        raise AssertionError("transport should not run")

    config = load_config({})
    assert config.is_configured is False
    assert "missing" in repr(config)
    client = _client(config, transport)
    result = client.get("caller/supplied")
    assert result["status"] == "not_configured"
    assert result["message"] == NOT_CONFIGURED_MESSAGE
    assert result["reason"] == "missing_configuration"
    assert client.fetch_projects()["status"] == "not_configured"
    assert called["count"] == 0


def test_url_without_credentials_sends_no_authorization_header():
    seen = {}

    def transport(url, headers, timeout):
        seen["headers"] = dict(headers)
        return 200, b'{"ok":true}'

    config = load_config(
        {
            "EXTERNAL_REAL_ESTATE_API_URL": _BASE,
            "EXTERNAL_REAL_ESTATE_API_TIMEOUT": "4",
        }
    )
    assert config.is_configured is True
    assert config.api_key is None
    assert config.timeout_seconds == 4.0
    result = _client(config, transport).get("caller/supplied")
    assert result["status"] == "ok"
    assert "Authorization" not in seen["headers"]


def test_http_error_hides_status_body_and_key():
    def transport(url, headers, timeout):
        return 401, f"rejected {_SECRET}".encode("utf-8")

    result = _client(_configured(), transport).get("caller/supplied")
    assert result["status"] == "unavailable"
    assert result["message"] == UNAVAILABLE_MESSAGE
    assert result["reason"] == "http_error"
    assert result["detail"] == "HTTP 401."
    assert result["data"] is None
    _assert_secret_hidden(result)


def test_timeout_and_url_error_timeout():
    def timeout_transport(url, headers, timeout):
        raise TimeoutError()

    timeout_result = _client(_configured(), timeout_transport).get("caller/supplied")
    assert timeout_result["reason"] == "timeout"
    assert timeout_result["detail"] == "The request timed out."
    assert timeout_result["message"] == UNAVAILABLE_MESSAGE
    _assert_secret_hidden(timeout_result)

    def url_timeout(url, headers, timeout):
        raise urllib.error.URLError(TimeoutError())

    url_result = _client(_configured(), url_timeout).get("caller/supplied")
    assert url_result["reason"] == "timeout"
    assert url_result["detail"] == "The request timed out."


def test_connection_failures():
    def refused(url, headers, timeout):
        raise urllib.error.URLError(OSError("refused"))

    refused_result = _client(_configured(), refused).get("caller/supplied")
    assert refused_result["reason"] == "connection"
    assert refused_result["detail"] == "The connection to the external API failed."
    assert "refused" not in json.dumps(refused_result)
    _assert_secret_hidden(refused_result)

    def os_error(url, headers, timeout):
        raise OSError("network down")

    os_result = _client(_configured(), os_error).get("caller/supplied")
    assert os_result["reason"] == "connection"
    assert "network down" not in json.dumps(os_result)


def test_invalid_json():
    def transport(url, headers, timeout):
        return 200, b"\xff not-json"

    result = _client(_configured(), transport).get("caller/supplied")
    assert result["reason"] == "invalid_json"
    assert result["detail"] == "The response was not valid JSON."
    assert result["message"] == UNAVAILABLE_MESSAGE
    assert result["data"] is None


def test_explicit_auth_none_does_not_send_a_stored_key():
    seen = {}

    def transport(url, headers, timeout):
        seen["headers"] = dict(headers)
        return 200, b"{}"

    config = load_config(
        {
            "EXTERNAL_REAL_ESTATE_API_URL": _BASE,
            "EXTERNAL_REAL_ESTATE_API_KEY": _SECRET,
            "EXTERNAL_REAL_ESTATE_API_AUTH": "none",
        }
    )
    assert config.auth_scheme == "none"
    assert _SECRET not in repr(config)
    result = _client(config, transport).get("caller/supplied")
    assert result["status"] == "ok"
    assert "Authorization" not in seen["headers"]
    _assert_secret_hidden(result)


def test_bearer_without_a_key_does_not_call_transport():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        raise AssertionError("transport should not run")

    config = ExternalAPIConfig(_BASE, None, 1, "bearer")
    result = _client(config, transport).get("caller/supplied")
    assert result["status"] == "not_configured"
    assert result["message"] == CREDENTIALS_NOT_CONFIGURED_MESSAGE
    assert result["reason"] == "missing_credentials"
    assert called["count"] == 0


def test_unsupported_auth_scheme_does_not_send_the_key():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        raise AssertionError("transport should not run")

    config = load_config(
        {
            "EXTERNAL_REAL_ESTATE_API_URL": _BASE,
            "EXTERNAL_REAL_ESTATE_API_KEY": _SECRET,
            "EXTERNAL_REAL_ESTATE_API_AUTH": _SECRET,
        }
    )
    assert "unsupported" in repr(config)
    assert _SECRET not in repr(config)
    result = _client(config, transport).get("caller/supplied")
    assert result["message"] == UNSUPPORTED_AUTH_MESSAGE
    assert result["reason"] == "unsupported_auth"
    _assert_secret_hidden(result)
    assert called["count"] == 0


def test_fetch_methods_stay_offline_when_the_client_is_configured():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        return 200, b"{}"

    client = _client(_configured(), transport)
    for method in (
        client.fetch_projects,
        client.fetch_market_data,
        client.fetch_pricing,
        client.fetch_rental_data,
    ):
        result = method()
        assert result["status"] == "unavailable"
        assert result["reason"] == "provider_adapter_not_registered"
        assert result["data"] is None
        _assert_secret_hidden(result)
    assert called["count"] == 0


def test_blank_path_does_not_invent_an_endpoint():
    called = {"count": 0}

    def transport(url, headers, timeout):
        called["count"] += 1
        raise AssertionError("transport should not run")

    result = _client(_configured(), transport).get("  ")
    assert result["reason"] == "provider_adapter_not_registered"
    assert called["count"] == 0
