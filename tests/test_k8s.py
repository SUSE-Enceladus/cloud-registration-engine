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

"""Unit tests for the k8s state persistence module."""

import json
import os
from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.exceptions import ApiException

from registration_engine.k8s import update_registration_data


@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_patch_success(mock_load_incluster, mock_v1_class):
    """Test successful patch of existing secret."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate read success (secret exists)
    mock_v1.read_namespaced_secret.return_value = MagicMock()

    # Call function
    instance_data = {"test_key": "test_val"}
    update_registration_data("10.0.0.1", "fake-cert", instance_data)

    mock_load_incluster.assert_called_once()
    mock_v1.read_namespaced_secret.assert_called_once_with(
        name="scc-registration", namespace="cattle-scc-system"
    )

    # Check patched call parameters
    mock_v1.patch_namespaced_secret.assert_called_once()
    args, kwargs = mock_v1.patch_namespaced_secret.call_args
    assert kwargs["name"] == "scc-registration"
    assert kwargs["namespace"] == "cattle-scc-system"
    body = kwargs["body"]
    assert body.string_data["registrationUrl"] == "10.0.0.1"
    assert body.string_data["registrationUrlCert"] == "fake-cert"
    assert json.loads(body.string_data["instanceData"]) == instance_data


@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_kube_config")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_create_success(
    mock_load_incluster, mock_load_kube, mock_v1_class
):
    """Test successful creation when secret does not exist."""
    mock_load_incluster.side_effect = Exception("Not in cluster")

    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate read raising 404 (secret doesn't exist)
    mock_v1.read_namespaced_secret.side_effect = ApiException(
        status=404, reason="Not Found"
    )

    # Call function
    instance_data = {"test_key": "test_val"}
    update_registration_data("10.0.0.1", "fake-cert", instance_data)

    mock_load_kube.assert_called_once()
    mock_v1.read_namespaced_secret.assert_called_once_with(
        name="scc-registration", namespace="cattle-scc-system"
    )

    mock_v1.create_namespaced_secret.assert_called_once()
    args, kwargs = mock_v1.create_namespaced_secret.call_args
    assert kwargs["namespace"] == "cattle-scc-system"
    body = kwargs["body"]
    assert body.type == "Opaque"
    assert body.string_data["registrationUrl"] == "10.0.0.1"


@patch("registration_engine.k8s.config.load_kube_config")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_config_failed(mock_load_incluster, mock_load_kube):
    """Test load config raises exception."""
    mock_load_incluster.side_effect = Exception("No cluster")
    mock_load_kube.side_effect = Exception("No local kube config")

    with pytest.raises(Exception, match="No local kube config"):
        update_registration_data("10.0.0.1", "cert", {})


@patch("registration_engine.k8s.time.sleep")
@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_api_error(
    mock_load_incluster, mock_v1_class, mock_sleep
):
    """Test API error 500 fails closed."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1

    # Simulate API error status 500
    mock_v1.read_namespaced_secret.side_effect = ApiException(
        status=500, reason="Internal Server Error"
    )

    with pytest.raises(RuntimeError, match="exhausted retries"):
        update_registration_data("10.0.0.1", "cert", {})

    assert mock_sleep.call_count == 4


@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_custom_env_config(
    mock_load_incluster, mock_v1_class
):
    """Test environment variable overrides."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1
    mock_v1.read_namespaced_secret.return_value = MagicMock()

    env_overrides = {
        "REGISTRATION_SECRET_NAME": "custom-secret",
        "REGISTRATION_SECRET_NAMESPACE": "custom-namespace",
        "REG_CODE": "custom-reg-code",
    }

    with patch.dict(os.environ, env_overrides):
        update_registration_data("10.0.0.1", "cert", {})

        mock_v1.read_namespaced_secret.assert_called_once_with(
            name="custom-secret", namespace="custom-namespace"
        )
        mock_v1.patch_namespaced_secret.assert_called_once()
        args, kwargs = mock_v1.patch_namespaced_secret.call_args
        body = kwargs["body"]
        assert body.string_data["registrationUrl"] == "10.0.0.1"


@patch("registration_engine.k8s.client.CoreV1Api")
@patch("registration_engine.k8s.config.load_incluster_config")
def test_update_registration_data_instance_data_string(
    mock_load_incluster, mock_v1_class
):
    """Test successful patch when instance_data is already a string."""
    mock_v1 = MagicMock()
    mock_v1_class.return_value = mock_v1
    mock_v1.read_namespaced_secret.return_value = MagicMock()

    update_registration_data("10.0.0.1", "cert", "raw_string_data")

    mock_v1.patch_namespaced_secret.assert_called_once()
    args, kwargs = mock_v1.patch_namespaced_secret.call_args
    body = kwargs["body"]
    assert body.string_data["instanceData"] == "raw_string_data"
