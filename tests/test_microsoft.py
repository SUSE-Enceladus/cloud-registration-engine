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
    _build_credential,
    _require_env,
    fetch_extension_plan,
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


@patch("registration_engine.microsoft.WorkloadIdentityCredential")
def test_build_credential_success(mock_cred_class):
    """Test _build_credential successfully creates credential."""
    env_vars = {
        "AZURE_TENANT_ID": "tenant-id",
        "AZURE_CLIENT_ID": "client-id",
        "AZURE_FEDERATED_TOKEN_FILE": "/path/to/token",
    }
    with patch.dict(os.environ, env_vars):
        _build_credential()
        mock_cred_class.assert_called_once_with(
            tenant_id="tenant-id",
            client_id="client-id",
            token_file_path="/path/to/token",
        )


@patch("registration_engine.microsoft.WorkloadIdentityCredential")
def test_build_credential_missing_env(mock_cred_class):
    """Test _build_credential raises RuntimeError on missing env."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError):
            _build_credential()


@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_success(mock_get):
    """Test fetch_extension_plan success."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "plan": {
            "publisher": "pub",
            "product": "prod",
            "name": "plan-id"
        }
    }
    mock_get.return_value = mock_resp

    plan = fetch_extension_plan(mock_cred, "/sub/resource")

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
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"something": "else"}
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError, match="has no plan{} block"):
        fetch_extension_plan(mock_cred, "/sub/resource")


@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_non_retryable_error(mock_get):
    """Test fetch_extension_plan fails immediately on non-retryable error."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.status_code = 403
    mock_resp.text = "Forbidden"
    mock_get.return_value = mock_resp

    with pytest.raises(RuntimeError, match="Non-retryable ARM error 403"):
        fetch_extension_plan(mock_cred, "/sub/resource")

    assert mock_get.call_count == 1


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_transient_retry_success(mock_get, mock_sleep):
    """Test fetch_extension_plan retries on 500 and then succeeds."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal Error"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "plan": {
            "publisher": "pub",
            "product": "prod",
            "name": "plan"
        }
    }

    mock_get.side_effect = [mock_resp_500, mock_resp_200]

    plan = fetch_extension_plan(mock_cred, "/sub/resource")
    assert plan.publisher_id == "pub"
    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_transient_retry_exhausted(mock_get, mock_sleep):
    """Test fetch_extension_plan retries and exhausts limits."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    mock_resp_500.text = "Internal Error"

    mock_get.return_value = mock_resp_500

    with pytest.raises(RuntimeError, match="ARM verification exhausted"):
        fetch_extension_plan(mock_cred, "/sub/resource")

    assert mock_get.call_count == 5


@patch("registration_engine.microsoft.fetch_extension_plan")
@patch("registration_engine.microsoft._build_credential")
def test_verify_once_success(mock_build_cred, mock_fetch_plan):
    """Test verify_once matches plan and returns it."""
    env_vars = {
        "EXTENSION_RESOURCE_ID": "/sub/resource",
        "MARKETPLACE_PUBLISHER_ID": "pub",
        "MARKETPLACE_OFFER_ID": "offer",
        "MARKETPLACE_PLAN_ID": "plan",
    }
    mock_fetch_plan.return_value = Plan("pub", "offer", "plan")

    with patch.dict(os.environ, env_vars):
        result = verify_once()
        assert result.publisher_id == "pub"
        assert result.offer_id == "offer"
        assert result.plan_id == "plan"


@patch("registration_engine.microsoft.fetch_extension_plan")
@patch("registration_engine.microsoft._build_credential")
def test_verify_once_mismatch(mock_build_cred, mock_fetch_plan):
    """Test verify_once raises RuntimeError on plan mismatch."""
    env_vars = {
        "EXTENSION_RESOURCE_ID": "/sub/resource",
        "MARKETPLACE_PUBLISHER_ID": "pub",
        "MARKETPLACE_OFFER_ID": "offer",
        "MARKETPLACE_PLAN_ID": "plan",
    }
    # Fetched plan doesn't match env plan (different plan name)
    mock_fetch_plan.return_value = Plan("pub", "offer", "different-plan")

    with patch.dict(os.environ, env_vars):
        with pytest.raises(RuntimeError, match="Plan mismatch detected"):
            verify_once()
