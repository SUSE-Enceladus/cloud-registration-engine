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

"""Chaos and resilience tests for the Kubernetes State Persistence module."""

import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from registration_engine.k8s import update_registration_data

MOCK_ENV = {
    "KUBERNETES_SERVICE_HOST": "127.0.0.1",
    "KUBERNETES_SERVICE_PORT": "8443",
    "KUBERNETES_TOKEN": "mocked-token",
    "KUBERNETES_CA_CERT": "False",
}


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_conflict_and_success(
    mock_get, mock_patch, mock_sleep
):
    """Chaos Test: Simulates HTTP 409 Conflict and recovers on next attempt."""
    # Read/get always returns 200 (secret exists)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200
    mock_get.return_value = mock_read_resp

    # First patch returns 409 (Conflict). Second patch returns 200 (Success).
    mock_patch_resp_409 = MagicMock()
    mock_patch_resp_409.status_code = 409
    mock_patch_resp_409.text = "Conflict"

    mock_patch_resp_200 = MagicMock()
    mock_patch_resp_200.status_code = 200

    mock_patch.side_effect = [mock_patch_resp_409, mock_patch_resp_200]

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_patch.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_rate_limiting_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates severe API server rate limiting (429)."""
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 429
    mock_read_resp.text = "Too Many Requests"
    mock_get.return_value = mock_read_resp

    with patch.dict(os.environ, MOCK_ENV):
        with pytest.raises(RuntimeError, match="exhausted retries"):
            update_registration_data("10.0.0.1", "cert", {})

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)
    mock_sleep.assert_any_call(8.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_socket_dropout_chaos(
    mock_get, mock_patch, mock_sleep
):
    """Chaos Test: Simulates transient TCP drops and socket dropouts."""
    # First get raises ConnectionResetError. Second get succeeds.
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200

    mock_get.side_effect = [
        requests.exceptions.ConnectionError("Connection reset by peer"),
        mock_read_resp,
    ]

    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch.return_value = mock_patch_resp

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_get.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.post")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_create_transient_error_chaos(
    mock_get, mock_post, mock_sleep
):
    """Chaos Test: Simulates transient error during secret creation."""
    # Simulate read raising 404 (needs creation)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 404
    mock_get.return_value = mock_read_resp

    # First post returns transient 409 conflict, second returns 201 success.
    mock_post_resp_409 = MagicMock()
    mock_post_resp_409.status_code = 409
    mock_post_resp_409.text = "Conflict"

    mock_post_resp_201 = MagicMock()
    mock_post_resp_201.status_code = 201

    mock_post.side_effect = [mock_post_resp_409, mock_post_resp_201]

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.post")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_create_non_transient_error_chaos(
    mock_get, mock_post, mock_sleep
):
    """Chaos Test: Simulates non-transient error during creation."""
    # Simulate read raising 404 (needs creation)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 404
    mock_get.return_value = mock_read_resp

    # Post returns 403 Forbidden (non-transient)
    mock_post_resp_403 = MagicMock()
    mock_post_resp_403.status_code = 403
    mock_post_resp_403.raise_for_status.side_effect = requests.HTTPError(
        "403 Client Error: Forbidden"
    )
    mock_post.return_value = mock_post_resp_403

    with patch.dict(os.environ, MOCK_ENV):
        with pytest.raises(requests.HTTPError, match="Forbidden"):
            update_registration_data("10.0.0.1", "cert", {})

    assert mock_post.call_count == 1
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_generic_exception_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates generic unexpected code crashes."""
    # Simulate generic exception on read
    mock_get.side_effect = Exception("System Crash")

    with patch.dict(os.environ, MOCK_ENV):
        with pytest.raises(RuntimeError, match="exhausted retries"):
            update_registration_data("10.0.0.1", "cert", {})

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4
