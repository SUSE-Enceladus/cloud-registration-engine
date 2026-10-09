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

"""Kubernetes State Persistence module using REST API."""

import json
import os

import requests

from registration_engine.coredns import (  # noqa: F401  (re-exported)
    process_corefile,
    process_custom_corefile,
    update_coredns_record,
)
from registration_engine.k8s_api import (
    TRANSIENT_STATUS_CODES,
    _run_with_retry,
    _TransientK8sError,
)
from registration_engine.provider import PROVIDER_UNKNOWN
from registration_engine.utils import get_logger

logger = get_logger()

TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_CERT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"


def get_k8s_api_base_url() -> str:
    """Constructs the internal Kubernetes API URL from env variables."""
    host = os.getenv("KUBERNETES_SERVICE_HOST")
    port = os.getenv("KUBERNETES_SERVICE_PORT")
    if not host or not port:
        logger.error("Kubernetes host or port environment variables missing.")
        raise RuntimeError("Kubernetes service host or port not configured.")
    return f"https://{host}:{port}"


def get_k8s_token(token_path: str = TOKEN_PATH) -> str:
    """Reads and returns the Kubernetes service account token."""
    try:
        if os.path.exists(token_path):
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
        else:
            token = os.getenv("KUBERNETES_TOKEN", "").strip()
            if not token:
                raise RuntimeError("Service account token not found.")
    except Exception as e:
        logger.error("Failed to load Kubernetes token: %s", e)
        raise e

    return token


def get_k8s_ca_cert_path(ca_cert_path: str = CA_CERT_PATH) -> str:
    """Verifies existence and returns the path to the Kubernetes CA cert."""
    if os.path.exists(ca_cert_path):
        verify = ca_cert_path
    else:
        verify_env = os.getenv("KUBERNETES_CA_CERT", "True").strip().lower()
        if verify_env == "false":
            verify = False
        else:
            verify = True

    return verify


def update_registration_data(
    registration_ip: str,
    fqdn: str,
    cert: str,
    instance_data: str | dict,
    provider: str = PROVIDER_UNKNOWN,
) -> None:
    """Store/patch compiled registration info back into K8s secret.

    The CoreDNS record for the FQDN is updated first. If that fails, the
    exception propagates and the secret is not written.

    Args:
        registration_ip: Active SMT routing IP address
        fqdn: Fully qualified domain name of the SMT server
        cert: Validated SMT certificate string
        instance_data: String or dictionary of collected instance data
        provider: Detected cloud provider, selects the CoreDNS update strategy
    """
    secret_name = os.getenv("REGISTRATION_SECRET_NAME", "scc-registration")

    # Discover host and port
    api_base_url = get_k8s_api_base_url()

    # Get k8s token and cert
    token = get_k8s_token()
    verify = get_k8s_ca_cert_path()

    # Make sure the SMT FQDN resolves in-cluster before storing registration data
    update_coredns_record(registration_ip, fqdn, api_base_url, token, verify, provider)

    namespace = os.getenv("REGISTRATION_SECRET_NAMESPACE", "cattle-scc-system")

    reg_code = os.getenv(
        "REGISTRATION_CODE",
        os.getenv("REG_CODE", os.getenv("REGCODE", "")),
    )

    # Format instance_data to JSON string if it's not already a string
    if not isinstance(instance_data, str):
        instance_data_str = json.dumps(instance_data)
    else:
        instance_data_str = instance_data

    string_data = {
        "registrationType": "online",
        "registrationUrl": f"https://{fqdn}",
        "regCode": reg_code,
        "instanceData": instance_data_str,
        "registrationUrlCert": cert,
    }

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    secret_url = f"{api_base_url}/api/v1/namespaces/{namespace}/secrets/{secret_name}"
    create_url = f"{api_base_url}/api/v1/namespaces/{namespace}/secrets"

    def attempt() -> None:
        # 1. Read to check if secret exists first
        read_resp = requests.get(secret_url, headers=headers, verify=verify, timeout=10)

        if read_resp.status_code == 200:
            # 2. Secret exists, patch it
            patch_headers = headers | {"Content-Type": "application/merge-patch+json"}
            patch_body = {"stringData": string_data}
            patch_resp = requests.patch(
                secret_url,
                json=patch_body,
                headers=patch_headers,
                verify=verify,
                timeout=10,
            )
            if patch_resp.status_code == 200:
                logger.info(
                    "Successfully patched secret %s in namespace %s",
                    secret_name,
                    namespace,
                )
                return
            if patch_resp.status_code in TRANSIENT_STATUS_CODES:
                raise _TransientK8sError(
                    f"Transient patch error {patch_resp.status_code}"
                )
            patch_resp.raise_for_status()
            raise _TransientK8sError(
                f"Unexpected patch status {patch_resp.status_code}"
            )

        if read_resp.status_code == 404:
            # 3. Secret doesn't exist, create it
            create_body = {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": secret_name},
                "type": "Opaque",
                "stringData": string_data,
            }
            create_resp = requests.post(
                create_url,
                json=create_body,
                headers=headers,
                verify=verify,
                timeout=10,
            )
            if create_resp.status_code in (200, 201):
                logger.info(
                    "Successfully created secret %s in namespace %s",
                    secret_name,
                    namespace,
                )
                return
            if create_resp.status_code in TRANSIENT_STATUS_CODES:
                raise _TransientK8sError(
                    f"Transient create error {create_resp.status_code}"
                )
            create_resp.raise_for_status()
            raise _TransientK8sError(
                f"Unexpected create status {create_resp.status_code}"
            )

        if read_resp.status_code in TRANSIENT_STATUS_CODES:
            raise _TransientK8sError(f"Transient read error {read_resp.status_code}")
        read_resp.raise_for_status()
        raise _TransientK8sError(f"Unexpected read status {read_resp.status_code}")

    _run_with_retry(attempt, "secret update")
