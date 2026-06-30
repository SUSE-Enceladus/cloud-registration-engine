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

"""Chaos and resilience tests for the microsoft module."""

from unittest.mock import MagicMock, patch

import requests
from azure.core.exceptions import AzureError

from registration_engine.microsoft import fetch_extension_plan


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_connection_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates extreme connection drops and network issues."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    # Sequence of events:
    # 1. Connection dropped
    # 2. Timeout
    # 3. HTTP 503 Service Unavailable
    # 4. Success 200
    mock_get.side_effect = [
        requests.exceptions.ConnectionError("Network card disappeared"),
        requests.exceptions.Timeout("Connection timed out"),
        MagicMock(status_code=503, text="Service Unavailable"),
        MagicMock(
            status_code=200,
            json=lambda: {
                "plan": {
                    "publisher": "pub",
                    "product": "prod",
                    "name": "plan"
                }
            }
        )
    ]

    plan = fetch_extension_plan(mock_cred, "/sub/resource")

    assert plan.publisher_id == "pub"
    assert mock_get.call_count == 4
    assert mock_sleep.call_count == 3  # slept after attempts 1, 2, and 3
    # Check that backoff delay grew exponentially: 1.0 -> 2.0 -> 4.0
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_rate_limiting_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates severe Azure ARM API rate limiting (429)."""
    mock_cred = MagicMock()
    mock_cred.get_token.return_value.token = "fake-token"

    # Simulate four 429 Rate Limits followed by a 200 Success
    mock_429 = MagicMock(status_code=429, text="Rate limit exceeded")
    mock_200 = MagicMock(
        status_code=200,
        json=lambda: {
            "plan": {
                "publisher": "pub",
                "product": "prod",
                "name": "plan"
            }
        }
    )

    mock_get.side_effect = [mock_429, mock_429, mock_429, mock_429, mock_200]

    plan = fetch_extension_plan(mock_cred, "/sub/resource")

    assert plan.publisher_id == "pub"
    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4  # slept after attempts 1, 2, 3, 4
    # Check exponential backoff delays: 1.0 -> 2.0 -> 4.0 -> 8.0
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)
    mock_sleep.assert_any_call(8.0)


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_azure_error_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates unexpected azure SDK/identity failures."""
    mock_cred = MagicMock()

    # Simulate get_token raising AzureError intermittently, then succeeding
    mock_cred.get_token.side_effect = [
        AzureError("MSAL authentication service is not responding"),
        MagicMock(token="fake-token")
    ]

    mock_resp = MagicMock(
        status_code=200,
        json=lambda: {
            "plan": {
                "publisher": "pub",
                "product": "prod",
                "name": "plan"
            }
        }
    )
    mock_get.return_value = mock_resp

    plan = fetch_extension_plan(mock_cred, "/sub/resource")

    assert plan.publisher_id == "pub"
    # First get_token call failed, fetch_extension_plan caught the AzureError,
    # retried, second get_token call worked, requests.get was executed once.
    assert mock_cred.get_token.call_count == 2
    assert mock_get.call_count == 1
    assert mock_sleep.call_count == 1
    mock_sleep.assert_any_call(1.0)
