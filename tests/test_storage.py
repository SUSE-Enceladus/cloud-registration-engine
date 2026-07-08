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

"""Unit tests for the Kubernetes detection & storage routing module."""

import os
from unittest.mock import patch

from registration_engine.storage import (
    check_kubernetes_environment,
    determine_environment,
)


@patch("os.path.exists")
def test_check_kubernetes_environment_via_env(mock_exists):
    """Test k8s detection via KUBERNETES_SERVICE_HOST environment variable."""
    mock_exists.return_value = False
    env_vars = {"KUBERNETES_SERVICE_HOST": "10.96.0.1"}

    with patch.dict(os.environ, env_vars, clear=True):
        assert check_kubernetes_environment() is True
        assert determine_environment() == "k8s"


@patch("os.path.exists")
def test_check_kubernetes_environment_via_token(mock_exists):
    """Test k8s detection via standard service account token file existence."""
    # Simulate /var/run/secrets/kubernetes.io/serviceaccount/token existing
    mock_exists.side_effect = lambda path: "serviceaccount/token" in path

    with patch.dict(os.environ, {}, clear=True):
        assert check_kubernetes_environment() is True
        assert determine_environment() == "k8s"


@patch("os.path.exists")
def test_check_kubernetes_environment_outside_k8s(mock_exists):
    """Test that k8s detection returns False outside a cluster."""
    mock_exists.return_value = False

    with patch.dict(os.environ, {}, clear=True):
        assert check_kubernetes_environment() is False
        assert determine_environment() == "local"
