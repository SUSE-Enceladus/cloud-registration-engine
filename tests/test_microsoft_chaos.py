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

import pytest
import requests

from registration_engine.microsoft import fetch_extension_plan


@patch("registration_engine.microsoft.time.sleep")
@patch("registration_engine.microsoft.requests.get")
def test_fetch_extension_plan_connection_chaos(mock_get, mock_sleep):
    """Chaos Test: Simulates extreme connection drops and network issues."""
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
                "plan": {"publisher": "pub", "product": "prod", "name": "plan"}
            },
        ),
    ]

    plan = fetch_extension_plan("fake-token", "/sub/resource")

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
    # Simulate four 429 Rate Limits followed by a 200 Success
    mock_429 = MagicMock(status_code=429, text="Rate limit exceeded")
    mock_200 = MagicMock(
        status_code=200,
        json=lambda: {"plan": {"publisher": "pub", "product": "prod", "name": "plan"}},
    )

    mock_get.side_effect = [mock_429, mock_429, mock_429, mock_429, mock_200]

    plan = fetch_extension_plan("fake-token", "/sub/resource")

    assert plan.publisher_id == "pub"
    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4  # slept after attempts 1, 2, 3, 4
    # Check exponential backoff delays: 1.0 -> 2.0 -> 4.0 -> 8.0
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)
    mock_sleep.assert_any_call(4.0)
    mock_sleep.assert_any_call(8.0)


@patch("registration_engine.microsoft.urllib.request.ProxyHandler")
@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_imds_proxy_bypass_and_success(mock_build_opener, mock_proxy_handler):
    """Chaos Test: Verify IMDS queries explicitly bypass proxy variables."""
    from registration_engine.microsoft import get_latest_api_version

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"apiVersions": ["2018-02-01", "2021-02-01"]}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    api_version = get_latest_api_version()

    assert api_version == "2021-02-01"
    # Verify ProxyHandler was called with {} to enforce proxy bypass
    mock_proxy_handler.assert_called_once_with({})


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_latest_api_version_missing_versions_chaos(mock_build_opener):
    """Chaos Test: Raise ValueError if versions list is empty."""
    from registration_engine.microsoft import get_latest_api_version

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    mock_response.read.return_value = b'{"apiVersions": []}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    with pytest.raises(ValueError, match="No API versions returned"):
        get_latest_api_version()


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_compute_metadata_missing_subscription_id_chaos(mock_build_opener):
    """Chaos Test: Raise ValueError if subscriptionId is missing in IMDS compute."""
    from registration_engine.microsoft import get_compute_metadata

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    # Missing subscriptionId
    mock_response.read.return_value = b'{"location": "eastus"}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    with pytest.raises(ValueError, match="subscriptionId is missing"):
        get_compute_metadata("2021-02-01")


@patch("registration_engine.microsoft.urllib.request.build_opener")
def test_get_attested_data_missing_signature_chaos(mock_build_opener):
    """Chaos Test: Raise ValueError if signature is missing in IMDS attested."""
    from registration_engine.microsoft import get_attested_data

    mock_opener = MagicMock()
    mock_build_opener.return_value = mock_opener

    mock_response = MagicMock()
    # Missing signature
    mock_response.read.return_value = b'{"encoding": "pkcs7"}'
    mock_response.__enter__.return_value = mock_response
    mock_opener.open.return_value = mock_response

    with pytest.raises(ValueError, match="signature is missing"):
        get_attested_data("some-nonce", "2021-02-01")
