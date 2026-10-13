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

"""Unit tests for the CoreDNS record management module."""

from unittest.mock import MagicMock, patch

import pytest

from registration_engine.coredns import (
    process_corefile,
    process_custom_corefile,
    update_coredns_record,
)


def test_overwrite_existing_fqdn():
    original = (
        ".:53 {\n    hosts {\n        1.1.1.1 api.com\n        fallthrough\n    }\n}"
    )
    result = process_corefile(original, "2.2.2.2", "api.com")
    assert "2.2.2.2 api.com" in result
    assert "1.1.1.1" not in result


def test_chaos_empty_or_none_corefile():
    with pytest.raises(ValueError, match="Corefile is empty"):
        process_corefile("   \n  ", "1.1.1.1", "api.com")


def test_chaos_missing_server_block():
    with pytest.raises(ValueError, match="Could not find standard server block"):
        process_corefile("random config data", "1.1.1.1", "api.com")


def test_chaos_substring_fqdn_trap():
    original = (
        ".:53 {\n    hosts {\n        10.0.0.1 myapi.com\n        fallthrough\n    }\n}"
    )
    result = process_corefile(original, "52.188.81.163", "api.com")
    assert "10.0.0.1 myapi.com" in result
    assert "52.188.81.163 api.com" in result


def test_chaos_trailing_comments_on_existing_line():
    original = (
        ".:53 {\n"
        "    hosts {\n"
        "        1.2.3.4 api.com # old entry\n"
        "        fallthrough\n"
        "    }\n"
        "}"
    )
    result = process_corefile(original, "2.2.2.2", "api.com")
    assert "2.2.2.2 api.com" in result
    assert "# old entry" not in result


@patch("registration_engine.k8s_api.requests.get")
@patch("registration_engine.k8s_api.requests.patch")
def test_requests_k8s_api_patch_coredns(mock_patch, mock_get):
    """Verifies the requests library executes the correct HTTP calls to K8s."""

    # Setup GET response mock
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = {"data": {"Corefile": ".:53 {\n}"}}
    mock_get.return_value = mock_get_response

    # Setup PATCH response mock
    mock_patch_response = MagicMock()
    mock_patch.return_value = mock_patch_response

    # Execute with injected test credentials
    test_base_url = "https://10.96.0.1:443"
    test_token = "fake-token"
    test_verify = "/fake/ca.crt"
    update_coredns_record(
        "52.188.81.163", "api.com", test_base_url, test_token, test_verify
    )

    # Verify GET Request
    mock_get.assert_called_once()
    get_url = mock_get.call_args[0][0]
    get_kwargs = mock_get.call_args[1]

    assert (
        get_url == f"{test_base_url}/api/v1/namespaces/kube-system/configmaps/coredns"
    )
    assert get_kwargs["headers"]["Authorization"] == f"Bearer {test_token}"
    assert get_kwargs["verify"] == test_verify

    # Verify PATCH Request
    mock_patch.assert_called_once()
    patch_url = mock_patch.call_args[0][0]
    patch_kwargs = mock_patch.call_args[1]

    assert (
        patch_url == f"{test_base_url}/api/v1/namespaces/kube-system/configmaps/coredns"
    )
    assert patch_kwargs["headers"]["Content-Type"] == "application/merge-patch+json"
    assert "52.188.81.163 api.com" in patch_kwargs["json"]["data"]["Corefile"]


# --- coredns-custom (Azure AKS) ---

BASE = "https://10.96.0.1:443"
CUSTOM_URL = f"{BASE}/api/v1/namespaces/kube-system/configmaps/coredns-custom"
CORE_URL = f"{BASE}/api/v1/namespaces/kube-system/configmaps/coredns"
DEPLOY_URL = f"{BASE}/apis/apps/v1/namespaces/kube-system/deployments/coredns"
AKS_ARGS = ("52.188.81.163", "api.com", BASE, "tok", False)


def _cm(status, data=None):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"data": data}
    return resp


def test_custom_empty_creates_hosts_block():
    result = process_custom_corefile("", "1.1.1.1", "api.com")
    assert result == "hosts {\n    1.1.1.1 api.com\n    fallthrough\n}\n"
    assert ".:53" not in result


def test_custom_none_creates_hosts_block():
    assert "1.1.1.1 api.com" in process_custom_corefile(None, "1.1.1.1", "api.com")


def test_custom_overwrite_existing_fqdn_keeps_indent():
    original = "hosts {\n    1.1.1.1 api.com\n    fallthrough\n}\n"
    result = process_custom_corefile(original, "2.2.2.2", "api.com")
    assert result == "hosts {\n    2.2.2.2 api.com\n    fallthrough\n}\n"


def test_custom_insert_into_existing_hosts_block():
    original = "hosts {\n    10.0.0.1 other.com\n    fallthrough\n}\n"
    result = process_custom_corefile(original, "2.2.2.2", "api.com")
    assert "10.0.0.1 other.com" in result
    assert "2.2.2.2 api.com" in result
    assert result.count("hosts {") == 1


def test_custom_appends_block_to_unrelated_content():
    result = process_custom_corefile("log\n", "1.1.1.1", "api.com")
    assert result.startswith("log\nhosts {")
    assert "1.1.1.1 api.com" in result


def test_custom_substring_fqdn_trap():
    original = "hosts {\n    10.0.0.1 myapi.com\n    fallthrough\n}\n"
    result = process_custom_corefile(original, "2.2.2.2", "api.com")
    assert "10.0.0.1 myapi.com" in result
    assert "2.2.2.2 api.com" in result


@pytest.mark.parametrize("start", ["", "hosts {\n    10.0.0.1 o.com\n}\n"])
def test_custom_idempotent(start):
    once = process_custom_corefile(start, "2.2.2.2", "api.com")
    assert process_custom_corefile(once, "2.2.2.2", "api.com") == once


@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_updates_custom_and_restarts(mock_get, mock_patch):
    mock_get.return_value = _cm(200, {"other.override": "log\n"})
    mock_patch.return_value = MagicMock(status_code=200)

    update_coredns_record(*AKS_ARGS, "microsoft")

    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == CUSTOM_URL
    assert mock_patch.call_count == 2

    cm_call, restart_call = mock_patch.call_args_list
    assert cm_call[0][0] == CUSTOM_URL
    assert cm_call[1]["headers"]["Content-Type"] == "application/merge-patch+json"
    # Only our own key is written
    assert list(cm_call[1]["json"]["data"]) == ["registration.override"]
    assert (
        "52.188.81.163 api.com" in cm_call[1]["json"]["data"]["registration.override"]
    )

    assert restart_call[0][0] == DEPLOY_URL
    annotations = restart_call[1]["json"]["spec"]["template"]["metadata"]["annotations"]
    assert "kubectl.kubernetes.io/restartedAt" in annotations


@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_custom_without_data_key(mock_get, mock_patch):
    """A coredns-custom ConfigMap with no data at all still gets our key."""
    mock_get.return_value = _cm(200, None)
    mock_patch.return_value = MagicMock(status_code=200)

    update_coredns_record(*AKS_ARGS, "microsoft")

    payload = mock_patch.call_args_list[0][1]["json"]
    assert "52.188.81.163 api.com" in payload["data"]["registration.override"]


@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_noop_does_not_write_or_restart(mock_get, mock_patch):
    current = process_custom_corefile("", "52.188.81.163", "api.com")
    mock_get.return_value = _cm(200, {"registration.override": current})

    update_coredns_record(*AKS_ARGS, "microsoft")

    assert mock_get.call_count == 1
    mock_patch.assert_not_called()


@patch("registration_engine.k8s_api.requests.post")
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_aks_missing_custom_falls_back_to_coredns(mock_get, mock_patch, mock_post):
    """coredns-custom is never created; the coredns ConfigMap is used instead."""
    core = MagicMock(status_code=200)
    core.json.return_value = {"data": {"Corefile": ".:53 {\n}"}}
    mock_get.side_effect = [MagicMock(status_code=404), core]
    mock_patch.return_value = MagicMock(status_code=200)

    update_coredns_record(*AKS_ARGS, "microsoft")

    assert [c[0][0] for c in mock_get.call_args_list] == [CUSTOM_URL, CORE_URL]
    mock_post.assert_not_called()
    mock_patch.assert_called_once()
    assert mock_patch.call_args[0][0] == CORE_URL


@pytest.mark.parametrize("provider", ["amazon", "google", "unknown"])
@patch("registration_engine.k8s_api.requests.patch")
@patch("registration_engine.k8s_api.requests.get")
def test_non_azure_provider_never_touches_custom(mock_get, mock_patch, provider):
    core = MagicMock(status_code=200)
    core.json.return_value = {"data": {"Corefile": ".:53 {\n}"}}
    mock_get.return_value = core
    mock_patch.return_value = MagicMock(status_code=200)

    update_coredns_record(*AKS_ARGS, provider)

    mock_get.assert_called_once()
    assert mock_get.call_args[0][0] == CORE_URL
    mock_patch.assert_called_once()
    assert mock_patch.call_args[0][0] == CORE_URL
