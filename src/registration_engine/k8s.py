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
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone

import requests

from registration_engine.provider import PROVIDER_MICROSOFT, PROVIDER_UNKNOWN
from registration_engine.utils import get_logger

logger = get_logger()

K8S_RETRY_MAX = int(os.getenv("K8S_RETRY_MAX", "5"))
K8S_RETRY_BACKOFF = float(os.getenv("K8S_RETRY_BACKOFF", "2.0"))
TRANSIENT_STATUS_CODES = (409, 429, 500, 502, 503, 504)
TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"
CA_CERT_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
COREDNS_NAMESPACE = "kube-system"
COREDNS_CONFIGMAP = "coredns"
COREDNS_DEPLOYMENT = "coredns"
# Azure AKS reconciles the "coredns" ConfigMap and reverts manual edits.
# Customisations go in the "coredns-custom" ConfigMap instead. Keys ending in
# ".override" are imported inside the default server block.
COREDNS_CUSTOM_CONFIGMAP = "coredns-custom"
COREDNS_CUSTOM_KEY = "registration.override"


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


def process_corefile(corefile: str, ip_address: str, fqdn: str) -> str:
    """Injects or updates a DNS mapping in the CoreDNS Corefile."""
    if not corefile or not corefile.strip():
        raise ValueError("Corefile is empty or invalid.")

    line_pattern = r"^[ \t]*\S+[ \t]+" + re.escape(fqdn) + r"(?=\s|$).*$"

    # Scenario 1: FQDN already exists -> Overwrite line
    if re.search(line_pattern, corefile, flags=re.MULTILINE):
        new_line = f"        {ip_address} {fqdn}"
        return re.sub(line_pattern, new_line, corefile, flags=re.MULTILINE)

    # Scenario 2: FQDN doesn't exist, but 'hosts {' block exists
    hosts_pattern = r"(hosts\s*\{)"
    if re.search(hosts_pattern, corefile):
        insertion = rf"\g<1>\n           {ip_address} {fqdn}"
        return re.sub(hosts_pattern, insertion, corefile, count=1)

    # Scenario 3: Neither exists -> Inject new hosts block into main server block
    server_block_pattern = r"(\.:53\s*\{)"
    if re.search(server_block_pattern, corefile):
        hosts_block = (
            f"\\g<1>\n"
            f"    hosts {{\n"
            f"        {ip_address} {fqdn}\n"
            f"        fallthrough\n"
            f"    }}"
        )
        return re.sub(server_block_pattern, hosts_block, corefile, count=1)

    raise ValueError("Could not find standard server block (.:53 {) in Corefile.")


def process_custom_corefile(override: str, ip_address: str, fqdn: str) -> str:
    """Injects or updates a DNS mapping in a coredns-custom ``.override`` snippet.

    An override snippet contains bare CoreDNS directives that AKS imports into
    the default ``.:53`` server block, so there is no server block wrapper.
    An empty snippet is valid (the key does not exist on the first run).
    """
    override = override or ""

    # Scenario 1: FQDN already exists -> Overwrite line, keeping indentation
    line_pattern = r"^([ \t]*)\S+[ \t]+" + re.escape(fqdn) + r"(?=\s|$).*$"
    if re.search(line_pattern, override, flags=re.MULTILINE):
        return re.sub(
            line_pattern,
            lambda m: f"{m.group(1)}{ip_address} {fqdn}",
            override,
            flags=re.MULTILINE,
        )

    # Scenario 2: FQDN doesn't exist, but 'hosts {' block exists
    hosts_pattern = r"(hosts\s*\{)"
    if re.search(hosts_pattern, override):
        return re.sub(
            hosts_pattern,
            lambda m: f"{m.group(1)}\n    {ip_address} {fqdn}",
            override,
            count=1,
        )

    # Scenario 3: Neither exists -> append a new hosts block
    hosts_block = f"hosts {{\n    {ip_address} {fqdn}\n    fallthrough\n}}\n"
    if override.strip():
        return override.rstrip("\n") + "\n" + hosts_block
    return hosts_block


class _TransientK8sError(RuntimeError):
    """Raised inside a retried operation to signal a retryable failure."""


def _run_with_retry(
    operation: Callable[[], None],
    description: str,
    fatal: tuple[type[Exception], ...] = (),
) -> None:
    """Run operation, retrying transient failures with exponential backoff.

    The operation is attempted up to K8S_RETRY_MAX times. It signals success by
    returning and a retryable failure by raising _TransientK8sError.
    Connection errors, timeouts and unexpected exceptions are also retried.

    Args:
        operation: Callable performing one full attempt.
        description: Short label used in log and error messages.
        fatal: Exception types (other than requests errors) that must be
            re-raised immediately instead of retried.

    Raises:
        requests.HTTPError: Non-transient HTTP error, raised immediately.
        RuntimeError: All retries were exhausted.
    """
    last_err: Exception | None = None
    delay = 1.0
    for attempt in range(1, K8S_RETRY_MAX + 1):
        try:
            operation()
            return
        except requests.HTTPError as e:
            logger.error(
                "Kubernetes %s failed with non-retryable error: %s", description, e
            )
            raise
        except requests.RequestException as e:
            last_err = e
        except fatal:
            raise
        except Exception as e:
            last_err = e

        logger.warning(
            "Kubernetes %s attempt %d/%d failed: %s",
            description,
            attempt,
            K8S_RETRY_MAX,
            last_err,
        )
        if attempt < K8S_RETRY_MAX:
            time.sleep(delay)
            delay *= K8S_RETRY_BACKOFF

    raise RuntimeError(f"Kubernetes {description} exhausted retries: {last_err}")


def _check_response(response: requests.Response, action: str) -> None:
    """Raise _TransientK8sError for retryable statuses, HTTPError otherwise."""
    if response.status_code in TRANSIENT_STATUS_CODES:
        raise _TransientK8sError(f"Transient {action} error {response.status_code}")
    response.raise_for_status()


def _update_coredns_configmap(
    ip_address: str, fqdn: str, api_url: str, headers: dict, verify: str | bool
) -> None:
    """One attempt at patching the Corefile in the standard coredns ConfigMap."""
    # 1. GET current ConfigMap
    response = requests.get(api_url, headers=headers, verify=verify, timeout=10)
    _check_response(response, "read")
    corefile = response.json().get("data", {}).get("Corefile", "")

    # 2. Process changes
    updated_corefile = process_corefile(corefile, ip_address, fqdn)

    if updated_corefile == corefile:
        logger.info("No changes required. Corefile is already up to date.")
        return

    # 3. PATCH the ConfigMap back
    patch_headers = headers | {"Content-Type": "application/merge-patch+json"}
    patch_payload = {"data": {"Corefile": updated_corefile}}

    patch_response = requests.patch(
        api_url,
        headers=patch_headers,
        json=patch_payload,
        verify=verify,
        timeout=10,
    )
    _check_response(patch_response, "patch")

    logger.info("Successfully patched %s -> %s in CoreDNS.", fqdn, ip_address)


def _restart_coredns(base_url: str, headers: dict, verify: str | bool) -> None:
    """Trigger a rollout restart of the CoreDNS deployment."""
    url = (
        f"{base_url}/apis/apps/v1/namespaces/{COREDNS_NAMESPACE}"
        f"/deployments/{COREDNS_DEPLOYMENT}"
    )
    restarted_at = datetime.now(timezone.utc).isoformat()
    payload = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {"kubectl.kubernetes.io/restartedAt": restarted_at}
                }
            }
        }
    }
    response = requests.patch(
        url,
        headers=headers | {"Content-Type": "application/merge-patch+json"},
        json=payload,
        verify=verify,
        timeout=10,
    )
    _check_response(response, "restart")
    logger.info("Triggered rollout restart of CoreDNS deployment.")


def _update_coredns_custom(
    ip_address: str, fqdn: str, base_url: str, headers: dict, verify: str | bool
) -> bool:
    """One attempt at updating the AKS coredns-custom ConfigMap.

    The ConfigMap is never created. Only the registration override key is
    written, leaving any other keys untouched.

    Returns:
        True if coredns-custom exists and was handled, False if it does not
        exist (the caller should fall back to the coredns ConfigMap).
    """
    api_url = (
        f"{base_url}/api/v1/namespaces/{COREDNS_NAMESPACE}"
        f"/configmaps/{COREDNS_CUSTOM_CONFIGMAP}"
    )
    response = requests.get(api_url, headers=headers, verify=verify, timeout=10)
    if response.status_code == 404:
        logger.info(
            "ConfigMap %s not found, falling back to %s.",
            COREDNS_CUSTOM_CONFIGMAP,
            COREDNS_CONFIGMAP,
        )
        return False
    _check_response(response, "read")

    override = (response.json().get("data") or {}).get(COREDNS_CUSTOM_KEY, "")
    updated_override = process_custom_corefile(override, ip_address, fqdn)

    if updated_override == override:
        logger.info("No changes required. %s is up to date.", COREDNS_CUSTOM_CONFIGMAP)
        return True

    patch_response = requests.patch(
        api_url,
        headers=headers | {"Content-Type": "application/merge-patch+json"},
        json={"data": {COREDNS_CUSTOM_KEY: updated_override}},
        verify=verify,
        timeout=10,
    )
    _check_response(patch_response, "patch")
    logger.info(
        "Successfully patched %s -> %s in %s.",
        fqdn,
        ip_address,
        COREDNS_CUSTOM_CONFIGMAP,
    )

    _restart_coredns(base_url, headers, verify)
    return True


def update_coredns_record(
    ip_address: str,
    fqdn: str,
    base_url: str,
    token: str,
    verify: str | bool,
    provider: str = PROVIDER_UNKNOWN,
) -> None:
    """
    Reads, patches, and writes back the CoreDNS config via K8s API using requests.

    On Azure (AKS) the coredns ConfigMap is reconciled by AKS, so the record is
    written to the existing coredns-custom ConfigMap and CoreDNS is restarted.
    If coredns-custom does not exist, or on any other provider, the coredns
    ConfigMap is patched directly.

    Transient failures (connection errors, timeouts, and HTTP 409/429/5xx) retry
    the whole read-modify-write cycle so a conflict re-reads the latest ConfigMap.

    Raises:
        ValueError: The Corefile could not be processed (not retried).
        requests.HTTPError: Non-transient HTTP error (not retried).
        RuntimeError: All retries were exhausted.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    api_url = (
        f"{base_url}/api/v1/namespaces/{COREDNS_NAMESPACE}"
        f"/configmaps/{COREDNS_CONFIGMAP}"
    )

    def attempt() -> None:
        if provider == PROVIDER_MICROSOFT and _update_coredns_custom(
            ip_address, fqdn, base_url, headers, verify
        ):
            return
        _update_coredns_configmap(ip_address, fqdn, api_url, headers, verify)

    _run_with_retry(attempt, "CoreDNS update", fatal=(ValueError,))


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
