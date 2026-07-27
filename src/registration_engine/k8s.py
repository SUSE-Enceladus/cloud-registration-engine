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
import time

import requests

from registration_engine.utils import get_logger

logger = get_logger()

K8S_RETRY_MAX = int(os.getenv("K8S_RETRY_MAX", "5"))
K8S_RETRY_BACKOFF = float(os.getenv("K8S_RETRY_BACKOFF", "2.0"))


def update_registration_data(
    registration_ip: str, cert: str, instance_data: str | dict
) -> None:
    """Store/patch compiled registration info back into K8s secret.

    Args:
        registration_ip: Active SMT routing IP address
        cert: Validated SMT certificate string
        instance_data: String or dictionary of collected instance data
    """
    secret_name = os.getenv("REGISTRATION_SECRET_NAME", "scc-registration")

    # Discover host and port
    host = os.getenv("KUBERNETES_SERVICE_HOST")
    port = os.getenv("KUBERNETES_SERVICE_PORT")
    if not host or not port:
        logger.error("Kubernetes host or port environment variables missing.")
        raise RuntimeError("Kubernetes service host or port not configured.")

    api_base_url = f"https://{host}:{port}"

    # Get service account credentials from files or env fallbacks
    token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    ca_cert_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    namespace_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

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

    if os.path.exists(ca_cert_path):
        verify = ca_cert_path
    else:
        verify_env = os.getenv("KUBERNETES_CA_CERT", "True").strip().lower()
        if verify_env == "false":
            verify = False
        else:
            verify = True

    if os.path.exists(namespace_path):
        try:
            with open(namespace_path, "r", encoding="utf-8") as f:
                namespace = f.read().strip()
        except Exception as e:
            logger.error("Failed to read Kubernetes namespace file: %s", e)
            raise e
    else:
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
        "registrationUrl": registration_ip,
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

    last_err = None
    delay = 1.0
    for attempt in range(1, K8S_RETRY_MAX + 1):
        try:
            # 1. Read to check if secret exists first
            read_resp = requests.get(
                secret_url, headers=headers, verify=verify, timeout=10
            )

            if read_resp.status_code == 200:
                # 2. Secret exists, patch it
                patch_headers = headers | {
                    "Content-Type": "application/merge-patch+json"
                }
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
                elif patch_resp.status_code in (409, 429, 500, 502, 503, 504):
                    last_err = RuntimeError(
                        f"Transient patch error {patch_resp.status_code}"
                    )
                else:
                    patch_resp.raise_for_status()

            elif read_resp.status_code == 404:
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
                elif create_resp.status_code in (409, 429, 500, 502, 503, 504):
                    last_err = RuntimeError(
                        f"Transient create error {create_resp.status_code}"
                    )
                else:
                    create_resp.raise_for_status()

            elif read_resp.status_code in (409, 429, 500, 502, 503, 504):
                last_err = RuntimeError(f"Transient read error {read_resp.status_code}")
            else:
                read_resp.raise_for_status()

        except requests.HTTPError as e:
            logger.error(
                "Failed to access secret %s in namespace %s: %s",
                secret_name,
                namespace,
                e,
            )
            raise e
        except requests.RequestException as e:
            last_err = e
        except Exception as ex:
            last_err = ex

        logger.warning(
            "Kubernetes secret update attempt %d/%d failed: %s",
            attempt,
            K8S_RETRY_MAX,
            last_err,
        )
        if attempt < K8S_RETRY_MAX:
            time.sleep(delay)
            delay *= K8S_RETRY_BACKOFF

    raise RuntimeError(f"Kubernetes secret update exhausted retries: {last_err}")
