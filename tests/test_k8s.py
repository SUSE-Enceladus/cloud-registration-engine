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

"""Unit tests for the Kubernetes State Persistence module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from registration_engine.k8s import (
    process_corefile,
    update_coredns_record,
    update_registration_data,
)

MOCK_ENV = {
    "KUBERNETES_SERVICE_HOST": "127.0.0.1",
    "KUBERNETES_SERVICE_PORT": "8443",
    "KUBERNETES_TOKEN": "mocked-token",
    "KUBERNETES_CA_CERT": "False",
}


@pytest.fixture(autouse=True)
def mock_coredns():
    """Isolate secret handling tests from the CoreDNS update call."""
    with patch("registration_engine.k8s.update_coredns_record") as mock:
        yield mock


@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_patch_success(mock_get, mock_patch):
    """Test successful patch of existing secret."""
    # 1. Mock GET to return 200 (secret exists)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200
    mock_get.return_value = mock_read_resp

    # 2. Mock PATCH to return 200 (patch success)
    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch.return_value = mock_patch_resp

    instance_data = {"test_key": "test_val"}

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data(
            "10.0.0.1", "smt.example.com", "fake-cert", instance_data
        )

    mock_get.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/cattle-scc-system/"
        "secrets/scc-registration",
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
        },
        verify=False,
        timeout=10,
    )
    mock_patch.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/cattle-scc-system/"
        "secrets/scc-registration",
        json={
            "stringData": {
                "registrationType": "online",
                "registrationUrl": "https://smt.example.com",
                "regCode": "",
                "instanceData": json.dumps(instance_data),
                "registrationUrlCert": "fake-cert",
            }
        },
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
            "Content-Type": "application/merge-patch+json",
        },
        verify=False,
        timeout=10,
    )


@patch("registration_engine.k8s.requests.post")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_create_success(mock_get, mock_post):
    """Test successful creation when secret does not exist."""
    # 1. Mock GET to return 404 (secret doesn't exist)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 404
    mock_get.return_value = mock_read_resp

    # 2. Mock POST to return 201 (creation success)
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 201
    mock_post.return_value = mock_post_resp

    instance_data = {"test_key": "test_val"}

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data(
            "10.0.0.1", "smt.example.com", "fake-cert", instance_data
        )

    mock_get.assert_called_once()
    mock_post.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/cattle-scc-system/secrets",
        json={
            "apiVersion": "v1",
            "kind": "Secret",
            "metadata": {"name": "scc-registration"},
            "type": "Opaque",
            "stringData": {
                "registrationType": "online",
                "registrationUrl": "https://smt.example.com",
                "regCode": "",
                "instanceData": json.dumps(instance_data),
                "registrationUrlCert": "fake-cert",
            },
        },
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
        },
        verify=False,
        timeout=10,
    )


def test_update_registration_data_config_failed():
    """Test load config raises exception when env variables are missing."""
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(RuntimeError, match="not configured"):
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_api_error(mock_get, mock_sleep):
    """Test API error 500 fails closed."""
    # Mock GET to return 500 (Internal Server Error)
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 500
    mock_read_resp.text = "Internal Server Error"
    mock_get.return_value = mock_read_resp

    with patch.dict(os.environ, MOCK_ENV):
        with pytest.raises(RuntimeError, match="exhausted retries"):
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    assert mock_get.call_count == 5
    assert mock_sleep.call_count == 4


@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_custom_env_config(mock_get, mock_patch):
    """Test environment variable overrides."""
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200
    mock_get.return_value = mock_read_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch.return_value = mock_patch_resp

    env_overrides = MOCK_ENV | {
        "REGISTRATION_SECRET_NAME": "custom-secret",
        "REGISTRATION_SECRET_NAMESPACE": "custom-namespace",
        "REG_CODE": "custom-reg-code",
    }

    with patch.dict(os.environ, env_overrides):
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    mock_get.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/custom-namespace/"
        "secrets/custom-secret",
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
        },
        verify=False,
        timeout=10,
    )


@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_instance_data_string(mock_get, mock_patch):
    """Test successful patch when instance_data is already a string."""
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200
    mock_get.return_value = mock_read_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch.return_value = mock_patch_resp

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data(
            "10.0.0.1", "smt.example.com", "cert", "raw_string_data"
        )

    mock_patch.assert_called_once()
    args, kwargs = mock_patch.call_args
    body = kwargs["json"]
    assert body["stringData"]["instanceData"] == "raw_string_data"
    assert body["stringData"]["registrationUrl"] == "https://smt.example.com"


@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_default_namespace(mock_get, mock_patch):
    """Test default namespace is cattle-scc-system when env var is unset."""
    mock_read_resp = MagicMock()
    mock_read_resp.status_code = 200
    mock_get.return_value = mock_read_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.status_code = 200
    mock_patch.return_value = mock_patch_resp

    env_without_ns = {
        k: v for k, v in MOCK_ENV.items() if k != "REGISTRATION_SECRET_NAMESPACE"
    }

    with patch.dict(os.environ, env_without_ns, clear=True):
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    mock_get.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/cattle-scc-system/"
        "secrets/scc-registration",
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
        },
        verify=False,
        timeout=10,
    )
    mock_patch.assert_called_once_with(
        "https://127.0.0.1:8443/api/v1/namespaces/cattle-scc-system/"
        "secrets/scc-registration",
        json={
            "stringData": {
                "registrationType": "online",
                "registrationUrl": "https://smt.example.com",
                "regCode": "",
                "instanceData": "{}",
                "registrationUrlCert": "cert",
            }
        },
        headers={
            "Authorization": "Bearer mocked-token",
            "Accept": "application/json",
            "Content-Type": "application/merge-patch+json",
        },
        verify=False,
        timeout=10,
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


@patch("registration_engine.k8s.requests.get")
@patch("registration_engine.k8s.requests.patch")
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


@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_updates_coredns_first(
    mock_get, mock_patch, mock_coredns
):
    """CoreDNS is updated once, with the discovered API credentials."""
    mock_get.return_value = MagicMock(status_code=200)
    mock_patch.return_value = MagicMock(status_code=200)

    with patch.dict(os.environ, MOCK_ENV):
        update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    mock_coredns.assert_called_once_with(
        "10.0.0.1", "smt.example.com", "https://127.0.0.1:8443", "mocked-token", False
    )


@patch("registration_engine.k8s.requests.post")
@patch("registration_engine.k8s.requests.patch")
@patch("registration_engine.k8s.requests.get")
def test_update_registration_data_coredns_failure_skips_secret(
    mock_get, mock_patch, mock_post, mock_coredns
):
    """A CoreDNS failure propagates and the secret is never touched."""
    mock_coredns.side_effect = RuntimeError("CoreDNS update exhausted retries")

    with patch.dict(os.environ, MOCK_ENV):
        with pytest.raises(RuntimeError, match="CoreDNS update"):
            update_registration_data("10.0.0.1", "smt.example.com", "cert", {})

    assert mock_get.call_count == 0
    assert mock_patch.call_count == 0
    assert mock_post.call_count == 0
