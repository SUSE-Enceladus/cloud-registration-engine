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

"""Chaos and resilience tests for the k8s state persistence module."""

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from registration_engine.k8s import update_registration_data


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_conflict_and_success(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates HTTP 409 Conflict and recovers on next attempt."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # First attempt raises 409 Conflict. Second attempt succeeds.
    mock_v1.read_namespaced_secret.return_value = MagicMock()
    mock_v1.patch_namespaced_secret.side_effect = [
        ApiException(status=409, reason="Conflict"),
        MagicMock(),
    ]

    update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.patch_namespaced_secret.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_rate_limiting_chaos(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates severe API server rate limiting (429)."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    mock_v1.read_namespaced_secret.side_effect = ApiException(
        status=429, reason="Too Many Requests"
    )

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.read_namespaced_secret.call_count == 5
    assert mock_sleep.call_count == 4
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)
    mock_sleep.assert_any_call(8.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_socket_dropout_chaos(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates transient TCP drops and socket dropouts."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # First read raises raw ConnectionError. Second succeeds.
    mock_v1.read_namespaced_secret.side_effect = [
        ConnectionResetError("Connection reset by peer"),
        MagicMock(),
    ]
    mock_v1.patch_namespaced_secret.return_value = MagicMock()

    update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.read_namespaced_secret.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_create_transient_error_chaos(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates transient error during secret creation."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate read raising 404 (needs creation)
    mock_v1.read_namespaced_secret.side_effect = ApiException(
        status=404, reason="Not Found"
    )

    # First create call raises transient 409 conflict, second succeeds.
    mock_v1.create_namespaced_secret.side_effect = [
        ApiException(status=409, reason="Conflict"),
        MagicMock(),
    ]

    update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.create_namespaced_secret.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_create_non_transient_error_chaos(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates non-transient error during creation."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate read raising 404 (needs creation)
    mock_v1.read_namespaced_secret.side_effect = ApiException(
        status=404, reason="Not Found"
    )

    # Create raises 403 Forbidden (non-transient)
    mock_v1.create_namespaced_secret.side_effect = ApiException(
        status=403, reason="Forbidden"
    )

    with pytest.raises(ApiException, match="Forbidden"):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.create_namespaced_secret.call_count == 1
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_generic_exception_chaos(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Chaos Test: Simulates generic unexpected code crashes."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate generic exception on read
    mock_v1.read_namespaced_secret.side_effect = Exception("System Crash")

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_v1.read_namespaced_secret.call_count == 5
    assert mock_sleep.call_count == 4
