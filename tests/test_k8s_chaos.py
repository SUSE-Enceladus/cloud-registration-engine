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

from registration_engine.k8s import update_coredns_record, update_registration_data

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
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

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
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

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
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

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
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

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
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

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
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4


COREDNS_ARGS = ("52.188.81.163", "api.com", "https://10.96.0.1:443", "tok", False)


def _resp(status, corefile=None):
    resp = MagicMock()
    resp.status_code = status
    if corefile is not None:
        resp.json.return_value = {"data": {"Corefile": corefile}}
    return resp


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_transient_get_chaos(mock_get, mock_patch, mock_sleep):
    """Chaos Test: GET returns 503 once, then succeeds."""
    mock_get.side_effect = [_resp(503), _resp(200, ".:53 {\n}")]
    mock_patch.return_value = _resp(200)

    update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 1
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_patch_conflict_rereads(mock_get, mock_patch, mock_sleep):
    """Chaos Test: PATCH 409 retries the full read-modify-write cycle."""
    mock_get.return_value = _resp(200, ".:53 {\n}")
    mock_patch.side_effect = [_resp(409), _resp(200)]

    update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_connection_error_chaos(mock_get, mock_patch, mock_sleep):
    """Chaos Test: Connection drops and timeouts are retried."""
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("reset"),
        requests.exceptions.Timeout("timed out"),
        _resp(200, ".:53 {\n}"),
    ]
    mock_patch.return_value = _resp(200)

    update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 3
    assert mock_sleep.call_count == 2


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_exhausted_retries(mock_get, mock_sleep):
    """Chaos Test: Persistent failure raises RuntimeError after all retries."""
    mock_get.return_value = _resp(429)

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_non_transient_error_not_retried(
    mock_get, mock_patch, mock_sleep
):
    """Chaos Test: 403 Forbidden is raised immediately."""
    resp = _resp(403)
    resp.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    mock_get.return_value = resp

    with pytest.raises(requests.HTTPError, match="Forbidden"):
        update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 1
    assert mock_patch.call_count == 0
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_bad_corefile_not_retried(mock_get, mock_sleep):
    """Chaos Test: An unprocessable Corefile raises ValueError without retry."""
    mock_get.return_value = _resp(200, "random config data")

    with pytest.raises(ValueError, match="Could not find standard server block"):
        update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 1
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_coredns_record_no_changes_skips_patch(mock_get, mock_patch, mock_sleep):
    """An up-to-date Corefile succeeds without patching."""
    corefile = ".:53 {\n    hosts {\n        52.188.81.163 api.com\n    }\n}"
    mock_get.return_value = _resp(200, corefile)

    update_coredns_record(*COREDNS_ARGS)

    assert mock_patch.call_count == 0
    assert mock_sleep.call_count == 0
