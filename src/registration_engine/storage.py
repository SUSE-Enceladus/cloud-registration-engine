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

"""Kubernetes environment detection and storage routing module."""

import os


def check_kubernetes_environment() -> bool:
    """Bulletproof Kubernetes detection.

    Checks environment variables first, falling back to the standard
    service account token file path on disk.

    Returns:
        True if running in a Kubernetes environment, False otherwise.
    """
    in_env = "KUBERNETES_SERVICE_HOST" in os.environ
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    token_exists = os.path.exists(token_path)
    return in_env or token_exists


def determine_environment() -> str:
    """Determine the active host runtime environment.

    Returns:
        "k8s" if in a Kubernetes cluster, "local" otherwise.
    """
    if check_kubernetes_environment():
        return "k8s"
    return "local"
