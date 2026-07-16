# Copyright (c) 2026 SUSE LLC. All rights reserved.
#
# This file is part of registration-engine. registration-engine provides an
# api and command line utilities for testing images in the Public Cloud.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Unit tests for the microsoft module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from registration_engine.microsoft import (
    Plan,
    _require_env,
    fetch_extension_plan,
    get_workload_identity_token,
    verify_once,
)


def test_require_env_success():
    """Test _require_env returns value when variable exists."""
    with patch.dict(os.environ, {"TEST_KEY": "some-value"}):
        assert _require_env("TEST_KEY") == "some-value"


def test_require_env_missing():
    """Test _require_env raises RuntimeError when missing/empty."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="Required env var missing"):
            _require_env("TEST_KEY")

    with patch.dict(os.environ, {"TEST_KEY": " "}):
        with pytest.raises(RuntimeError, match="Required env var missing"):
            _require_env("TEST_KEY")


@patch("registration_engine.microsoft.requests.post")
@patch("builtins.open", new_callable=MagicMock)
def test_get_workload_identity_token_success(mock_open, mock_post):
    """Test get_workload_identity_token successfully retrieves token."""
    env_vars = {
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_FEDERATED_TOKEN_FILE": "/path/to/token",
    }
    mock_file = MagicMock()
    mock_file.read.return_value = "federated-jwt-token"
    mock_open.return_value.__enter__.return_value = mock_file

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"access_token": "retrieved-azure-token"}
    mock_post.return_value = mock_resp

    with patch.dict(os.environ, env_vars):
        token = get_workload_identity_token()
        assert token == "retrieved-azure-token"

    mock_open.assert_called_once_with("/path/to/token", "r", encoding="utf-8")
    assertion_type = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    mock_post.assert_called_once_with(
        "https://login.microsoftonline.com/tenant-id/oauth2/v2.0/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "client-id",
            "client_assertion_type": assertion_type,
            "client_assertion": "federated-jwt-token",
            "scope": "https://management.azure.com/.default",
        },
        timeout=10,
    )


def test_get_workload_identity_token_missing_env():
    """Test get_workload_identity_token raises RuntimeError on missing env."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError):
            get_workload_identity_token()


@patch("builtins.open", side_effect=OSError("Permission denied"))
def test_get_workload_identity_token_file_error(mock_open):
    """Test get_workload_identity_token raises RuntimeError on file read error."""
    env_vars = {
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_FEDERATED_TOKEN_FILE": "/path/to/token",
    }
    with patch.dict(os.environ, env_vars):
        with pytest.raises(RuntimeError, match="Failed to read federated token file"):
            get_workload_identity_token()


@patch("registration_engine.microsoft.requests.post")
@patch("builtins.open")
def test_get_workload_identity_token_request_error(mock_open, mock_post):
    """Test get_workload_identity_token raises RuntimeError on failed request."""
    env_vars = {
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_FEDERATED_TOKEN_FILE": "/path/to/token",
    }
    mock_file = MagicMock()
    mock_file.read.return_value = "federated-jwt-token"
    mock_open.return_value.__enter__.return_value = mock_file

    import requests

    mock_post.side_effect = requests.RequestException("Network error")

    with patch.dict(os.environ, env_vars):
        with pytest.raises(RuntimeError, match="Azure AD token request failed"):
            get_workload_identity_token()


@patch("registration_engine.microsoft.requests.post")
@patch("builtins.open")
def test_get_workload_identity_token_missing_token_in_json(mock_open, mock_post):
    """Test get_workload_identity_token raises RuntimeError when response
    lacks token.
    """
    env_vars = {
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_FEDERATED_TOKEN_FILE": "/path/to/token",
    }
    mock_file = MagicMock()
    mock_file.read.return_value = "federated-jwt-token"
    mock_open.return_value.__enter__.return_value = mock_file

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"error": "some_error"}
    mock_post.return_value = mock_resp

    with patch.dict(os.environ, env_vars):
        with pytest.raises(RuntimeError, match="Access token missing"):
            get_workload_identity_token()


@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_success(mock_get):
    """Test fetch_extension_plan success."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "plan": {"publisher": "pub", "product": "prod", "name": "plan-id"}
    }
    mock_get.return_value = mock_resp

    plan = fetch_extension_plan("fake-token", "/sub/resource")

    assert plan.publisher_id == "pub"
    assert plan.offer_id == "prod"
    assert plan.plan_id == "plan-id"
    mock_get.assert_called_once_with(
        "https://management.azure.com/sub/resource?api-version=2023-05-01",
        headers={
            "Authorization": "Bearer fake-token",
            "Accept": "application/json",
        },
        timeout=10,
    )


@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_missing_plan_block(mock_get):
    """Test fetch_extension_plan fails when plan block is absent."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"something": "else"}
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError, match="has no plan{} block"):
        fetch_extension_plan("fake-token", "/sub/resource")


@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_non_retryable_error(mock_get):
    """Test fetch_extension_plan fails immediately on non-retryable error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Non-retryable ARM error 403"):
        fetch_extension_plan("fake-token", "/sub/resource")

    assert mock_get.call_count == 1


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_transient_retry_success(mock_get, mock_sleep):
    """Test fetch_extension_plan retries on 500 and then succeeds."""
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal Error"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "plan": {"publisher": "pub", "product": "prod", "name": "plan"}
    }

    mock_get.side_effect = [mock_resp_500, mock_resp_200]

    plan = fetch_extension_plan("fake-token", "/sub/resource")
    assert plan.publisher_id == "pub"
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_transient_retry_exhausted(mock_get, mock_sleep):
    """Test fetch_extension_plan retries and exhausts limits."""
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal Error"

    mock_get.return_value = mock_resp_500

    with pytest.raises(RuntimeError, match="ARM verification exhausted"):
        fetch_extension_plan("fake-token", "/sub/resource")

    assert mock_get.call_count == 5


@patch("registration_engine.microsoft.fetch_extension_plan")
@patch("registration_engine.microsoft.get_workload_identity_token")
def test_verify_once_success(mock_get_token, mock_fetch_plan):
    """Test verify_once matches plan and returns it."""
    env_vars = {
        "EXTENSION_RESOURCE_ID": "/sub/resource",
        "MARKETPLACE_PUBLISHER_ID": "pub",
        "MARKETPLACE_OFFER_ID": "offer",
        "MARKETPLACE_PLAN_ID": "plan",
    }
    mock_get_token.return_value = "fake-token"
    mock_fetch_plan.return_value = Plan("pub", "offer", "plan")

    with patch.dict(os.environ, env_vars):
        result = verify_once()
        assert result.publisher_id == "pub"
        assert result.offer_id == "offer"
        assert result.plan_id == "plan"


@patch("registration_engine.microsoft.fetch_extension_plan")
@patch("registration_engine.microsoft.get_workload_identity_token")
def test_verify_once_mismatch(mock_get_token, mock_fetch_plan):
    """Test verify_once raises RuntimeError on plan mismatch."""
    env_vars = {
        "EXTENSION_RESOURCE_ID": "/sub/resource",
        "MARKETPLACE_PUBLISHER_ID": "pub",
        "MARKETPLACE_OFFER_ID": "offer",
        "MARKETPLACE_PLAN_ID": "plan",
    }
    mock_get_token.return_value = "fake-token"
    # Fetched plan doesn't match env plan (different plan name)
    mock_fetch_plan.return_value = Plan("pub", "offer", "different-plan")

    with patch.dict(os.environ, env_vars):
        with pytest.raises(RuntimeError, match="Plan mismatch detected"):
            verify_once()


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_latest_api_version_success(mock_build_opener):
    """Test get_latest_api_version parses sorted versions correctly."""
    from registration_engine.microsoft import get_latest_api_version

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    mock_response.read.return_value = (
        b'{"apiVersions": ["2018-02-01", "2023-01-01", "2021-02-01"]}'
    )
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    assert get_latest_api_version() == "2023-01-01"


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_compute_metadata_success(mock_build_opener):
    """Test get_compute_metadata extracts subscriptionId."""
    from registration_engine.microsoft import get_compute_metadata

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"subscriptionId": "sub-uuid-1234"}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    meta = get_compute_metadata("2021-02-01")
    assert meta["subscriptionId"] == "sub-uuid-1234"


def test_generate_nonce_success():
    """Test generate_nonce hashes offer into 32-char urlsafe b64 string."""
    from registration_engine.microsoft import generate_nonce

    nonce = generate_nonce("suse:sles-15-sp7:premium")
    assert isinstance(nonce, str)
    assert len(nonce) == 32
    # Verify urlsafe base64 character set
    assert "/" not in nonce and "+" not in nonce


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_attested_data_success(mock_build_opener):
    """Test get_attested_data retrieves signature."""
    from registration_engine.microsoft import get_attested_data

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"signature": "pkcs7-signature-bytes"}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    attested = get_attested_data("fake-nonce", "2021-02-01")
    assert attested["attestedData"]["signature"] == "pkcs7-signature-bytes"


@patch("registration_engine.microsoft.get_attested_data")
@patch("registration_engine.microsoft.generate_nonce")
@patch("registration_engine.microsoft.get_compute_metadata")
@patch("registration_engine.microsoft.get_latest_api_version")
@patch("registration_engine.microsoft.verify_once")
def test_get_verification_data_success(
    mock_verify, mock_api_version, mock_meta, mock_nonce, mock_attested
):
    """Test unified get_verification_data workflow and XML layout."""
    import json
    from xml.etree import ElementTree

    from registration_engine.microsoft import get_verification_data

    mock_verify.return_value = Plan("pub-id", "off-id", "pl-id")
    mock_api_version.return_value = "2021-02-01"
    mock_meta.return_value = {"subscriptionId": "sub-123"}
    mock_nonce.return_value = "hash-123"
    mock_attested.return_value = {"attestedData": {"signature": "sig-123"}}

    xml_str = get_verification_data()

    # Parse and assert XML format and JSON document data
    root = ElementTree.fromstring(xml_str)
    assert root.tag == "document"
    parsed_json = json.loads(root.text)
    assert parsed_json["offer"] == "pub-id:off-id:pl-id"
    assert parsed_json["subscriptionId"] == "sub-123"
    assert parsed_json["attestedData"]["signature"] == "sig-123"
