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

"""Chaos tests for the CoreDNS record management module."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from registration_engine.coredns import process_custom_corefile, update_coredns_record

COREDNS_ARGS = ("52.188.81.163", "api.com", "https://10.96.0.1:443", "tok", False)


def _resp(status, corefile=None):
    resp = MagicMock()
    resp.status_code = status
    if corefile is not None:
        resp.json.return_value = {"data": {"Corefile": corefile}}
    return resp


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_update_coredns_record_transient_get_chaos(mock_get, mock_patch, mock_sleep):
    """Chaos Test: GET returns 503 once, then succeeds."""
    mock_get.side_effect = [_resp(503), _resp(200, ".:53 {\n}")]
    mock_patch.return_value = _resp(200)

    update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 1
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_update_coredns_record_patch_conflict_rereads(mock_get, mock_patch, mock_sleep):
    """Chaos Test: PATCH 409 retries the full read-modify-write cycle."""
    mock_get.return_value = _resp(200, ".:53 {\n}")
    mock_patch.side_effect = [_resp(409), _resp(200)]

    update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
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


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.get")
def test_update_coredns_record_exhausted_retries(mock_get, mock_sleep):
    """Chaos Test: Persistent failure raises RuntimeError after all retries."""
    mock_get.return_value = _resp(429)

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
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


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.get")
def test_update_coredns_record_bad_corefile_not_retried(mock_get, mock_sleep):
    """Chaos Test: An unprocessable Corefile raises ValueError without retry."""
    mock_get.return_value = _resp(200, "random config data")

    with pytest.raises(ValueError, match="Could not find standard server block"):
        update_coredns_record(*COREDNS_ARGS)

    assert mock_get.call_count == 1
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_update_coredns_record_no_changes_skips_patch(mock_get, mock_patch, mock_sleep):
    """An up-to-date Corefile succeeds without patching."""
    corefile = ".:53 {\n    hosts {\n        52.188.81.163 api.com\n    }\n}"
    mock_get.return_value = _resp(200, corefile)

    update_coredns_record(*COREDNS_ARGS)

    assert mock_patch.call_count == 0
    assert mock_sleep.call_count == 0


# --- coredns-custom (Azure AKS) ---


def _cm_resp(status, override=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"data": {"registration.override": override or ""}}
    return resp


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_transient_get_chaos(mock_get, mock_patch, mock_sleep):
    """Chaos Test: coredns-custom GET returns 503 once, then succeeds."""
    mock_get.side_effect = [_resp(503), _cm_resp(200)]
    mock_patch.return_value = _resp(200)

    update_coredns_record(*COREDNS_ARGS, "microsoft")

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 2  # ConfigMap patch + restart
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_patch_conflict_rereads(mock_get, mock_patch, mock_sleep):
    """Chaos Test: PATCH 409 on coredns-custom retries the full cycle."""
    mock_get.return_value = _cm_resp(200)
    mock_patch.side_effect = [_resp(409), _resp(200), _resp(200)]

    update_coredns_record(*COREDNS_ARGS, "microsoft")

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 3
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_restart_transient_failure_retries_attempt(
    mock_get, mock_patch, mock_sleep
):
    """A transient restart failure retries the attempt (known gap: re-read
    sees the written record, so the second attempt does not write or restart).
    """
    written = process_custom_corefile("", "52.188.81.163", "api.com")
    mock_get.side_effect = [_cm_resp(200), _cm_resp(200, written)]
    mock_patch.side_effect = [_resp(200), _resp(503)]

    update_coredns_record(*COREDNS_ARGS, "microsoft")

    assert mock_get.call_count == 2
    assert mock_patch.call_count == 2
    mock_sleep.assert_called_once_with(1.0)


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_restart_non_transient_error_raises(mock_get, mock_patch, mock_sleep):
    """Chaos Test: 403 on the CoreDNS restart propagates immediately."""
    forbidden = _resp(403)
    forbidden.raise_for_status.side_effect = requests.HTTPError("403 Forbidden")
    mock_get.return_value = _cm_resp(200)
    mock_patch.side_effect = [_resp(200), forbidden]

    with pytest.raises(requests.HTTPError, match="Forbidden"):
        update_coredns_record(*COREDNS_ARGS, "microsoft")

    assert mock_patch.call_count == 2
    assert mock_sleep.call_count == 0


@patch("registration_engine.k8s_api.time.sleep")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_exhausted_retries(mock_get, mock_sleep):
    """Chaos Test: persistent 429 on coredns-custom raises after all retries."""
    mock_get.return_value = _resp(429)

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_coredns_record(*COREDNS_ARGS, "microsoft")

    assert mock_get.call_count == 5
