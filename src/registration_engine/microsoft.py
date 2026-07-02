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

"""Microsoft Workload Identity & Metadata Collection module."""

import base64
import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests

from registration_engine.utils import get_logger

ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
EXT_API_VERSION = "2023-05-01"
IMDS_BASE_URL = "http://169.254.169.254/metadata"
HEADERS = {"Metadata": "true"}

log = get_logger()

VERIFY_RETRY_MAX = int(os.getenv("VERIFY_RETRY_MAX", "5"))
VERIFY_RETRY_BACKOFF = float(os.getenv("VERIFY_RETRY_BACKOFF", "2.0"))


def _require_env(name: str) -> str:
    """
    Get the environment variable or raise RuntimeError if not set

    Args:
        name: The name of the environment variable to retrieve.

    Returns:
        The environment variable if it is set.
    """
    val = os.getenv(name, "").strip()
    if not val:
        raise RuntimeError(f"Required env var missing or empty: {name}")
    return val


def get_workload_identity_token(scope: str = ARM_SCOPE) -> str:
    """Retrieve an access token from Azure AD using Workload Identity.

    Fail if environment variables are missing or token exchange fails.

    Returns:
        The raw access token string.
    """
    tenant_id = _require_env("AZURE_TENANT_ID")
    client_id = _require_env("AZURE_CLIENT_ID")
    token_file_path = _require_env("AZURE_FEDERATED_TOKEN_FILE")

    try:
        with open(token_file_path, "r", encoding="utf-8") as f:
            federated_token = f.read().strip()
    except OSError as e:
        log.error("Failed to read federated token file: %s", e)
        raise RuntimeError(f"Failed to read federated token file: {e}") from e

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    assertion_type = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_assertion_type": assertion_type,
        "client_assertion": federated_token,
        "scope": scope,
    }

    try:
        resp = requests.post(token_url, data=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as e:
        log.error("Azure AD token request failed: %s", e)
        raise RuntimeError(f"Azure AD token request failed: {e}") from e

    access_token = data.get("access_token")
    if not access_token:
        log.error("Access token missing in OAuth response.")
        raise RuntimeError("Access token missing in OAuth response")

    return access_token


@dataclass(frozen=True)
class Plan:
    publisher_id: str
    offer_id: str
    plan_id: str

    @classmethod
    def from_arm(cls, plan_block: dict[str, Any]) -> "Plan":
        return cls(
            publisher_id=plan_block["publisher"],
            offer_id=plan_block["product"],
            plan_id=plan_block["name"],
        )

    @classmethod
    def from_env(cls) -> "Plan":
        return cls(
            publisher_id=_require_env("MARKETPLACE_PUBLISHER_ID"),
            offer_id=_require_env("MARKETPLACE_OFFER_ID"),
            plan_id=_require_env("MARKETPLACE_PLAN_ID"),
        )


def fetch_extension_plan(
    token: str, extension_resource_id: str
) -> Plan:
    """Fetch extension plan block using ARM Identity.

    Retries with exponential backoff on transient (5xx, 429, network) errors.
    Non-retryable HTTP errors (401/403/404) fail-closed immediately.

    Args:
        token: Azure Management Bearer token string
        extension_resource_id: Resource ID of the extension

    Returns:
        Plan dictionary
    """
    url = f"{ARM_ENDPOINT}{extension_resource_id}?api-version={EXT_API_VERSION}"

    last_err: Optional[Exception] = None
    delay = 1.0
    for attempt in range(1, VERIFY_RETRY_MAX + 1):
        try:
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                body = resp.json()
                plan_block = body.get("plan")
                if not plan_block:
                    raise RuntimeError(
                        f"Extension resource {extension_resource_id} has no "
                        "plan{} block (was it deployed via Marketplace?)"
                    )
                return Plan.from_arm(plan_block)
            if resp.status_code in (429, 500, 502, 503, 504):
                last_err = RuntimeError(
                    f"Transient ARM error {resp.status_code}: {resp.text[:200]}"
                )
            else:
                raise RuntimeError(
                    f"Non-retryable ARM error {resp.status_code}: {resp.text[:500]}"
                )
        except requests.RequestException as e:
            last_err = e

        log.warning(
            "ARM verification attempt %d/%d failed: %s",
            attempt,
            VERIFY_RETRY_MAX,
            last_err,
        )
        if attempt < VERIFY_RETRY_MAX:
            time.sleep(delay)
            delay *= VERIFY_RETRY_BACKOFF

    raise RuntimeError(f"ARM verification exhausted retries: {last_err}")


def _make_imds_request(url: str, timeout: int = 5) -> str:
    """Helper to perform an IMDS HTTP request.

    Explicitly bypasses any system-wide proxy variables.
    """
    req = urllib.request.Request(url, headers=HEADERS)
    # Build a dedicated opener with empty ProxyHandler to enforce proxy bypass
    proxy_support = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(proxy_support)

    try:
        with opener.open(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except Exception as e:
        log.error("IMDS request to %s failed: %s", url, e)
        raise e


def get_latest_api_version() -> str:
    """Query IMDS versions endpoint for the latest API string.

    Returns:
        Latest API version string
    """
    url = f"{IMDS_BASE_URL}/versions"
    try:
        response_body = _make_imds_request(url)
        data = json.loads(response_body)
        versions = data.get("apiVersions", [])
        if not versions:
            raise ValueError("No API versions returned from IMDS.")
        return sorted(versions)[-1]
    except Exception as e:
        log.error("Error fetching API versions from IMDS: %s", e)
        raise


def get_compute_metadata(api_version: str) -> Dict[str, Any]:
    """Query compute IMDS and extract subscriptionId.

    Args:
        api_version: IMDS API version

    Returns:
        Metadata dictionary containing subscriptionId
    """
    url = f"{IMDS_BASE_URL}/instance/compute?api-version={api_version}"
    try:
        response_body = _make_imds_request(url)
        compute_data = json.loads(response_body)
        subscription_id = compute_data.get("subscriptionId")
        if not subscription_id:
            raise ValueError("subscriptionId is missing in IMDS compute metadata.")
        return {"subscriptionId": subscription_id}
    except Exception as e:
        log.error("Error fetching compute metadata from IMDS: %s", e)
        raise


def generate_nonce(offer: str) -> str:
    """Hash authoritative plan block and return a URL-safe Base64 encoded nonce

    Args:
        offer: Authoritative plan URN

    Returns:
        32-character SHA-3-256 base64 encoded nonce string
    """
    try:
        sha3_bytes = hashlib.sha3_256(offer.encode("utf-8")).digest()
        b64_encoded = base64.urlsafe_b64encode(sha3_bytes).decode("utf-8")
        return b64_encoded[:32]
    except Exception as e:
        log.error("Failed to generate nonce hash: %s", e)
        raise


def get_attested_data(nonce: str, api_version: str) -> Dict[str, Any]:
    """Query attested endpoint using the nonce and API version.

    Args:
        nonce: Cryptographic nonce
        api_version: IMDS API version

    Returns:
        Dictionary containing pkcs7 signature, subscription ID and
        plain text nonce
    """
    url = (
        f"{IMDS_BASE_URL}/attested/document?api-version={api_version}&nonce={nonce}"
    )
    try:
        response_body = _make_imds_request(url)
        attested_data = json.loads(response_body)
        signature = attested_data.get("signature")
        if not signature:
            raise ValueError("signature is missing in IMDS attested document.")
        return {"attestedData": {"signature": signature}}
    except Exception as e:
        log.error("Error fetching attested data from IMDS: %s", e)
        raise


def verify_once() -> Plan:
    """
    Perform one verification round. Returns the authoritative Plan or raises.

    Returns:
        Plan object with the authoritive plan information.
    """
    extension_resource_id = _require_env("EXTENSION_RESOURCE_ID")
    env_plan = Plan.from_env()
    token = get_workload_identity_token()

    authoritative = fetch_extension_plan(token, extension_resource_id)

    if authoritative != env_plan:
        log.error(
            "Plan mismatch! ARM=%s ENV=%s - possible tampering. Failing closed.",
            authoritative,
            env_plan,
        )
        raise RuntimeError("Plan mismatch detected")

    log.info(
        "Plan verified: publisher=%s offer=%s plan=%s",
        authoritative.publisher_id,
        authoritative.offer_id,
        authoritative.plan_id,
    )
    return authoritative


def get_verification_data() -> str:
    """Retrieve the attested data with the authoritative plan information.

    Performs Microsoft Workload Identity plan verification internally, hashes the plan
    URN to a 32-character base64 nonce, queries the IMDS attested endpoint, and
    formats the signature and subscription metadata into an XML string.

    Returns:
        An XML formatted verification string.
    """
    verified_plan = verify_once()

    # Generate the URN (offer URN format: "publisher:offer:plan")
    offer_urn = (
        f"{verified_plan.publisher_id}:{verified_plan.offer_id}:{verified_plan.plan_id}"
    )

    api_version = get_latest_api_version()
    metadata = get_compute_metadata(api_version)
    nonce = generate_nonce(offer_urn)
    attested = get_attested_data(nonce, api_version)

    # Wrap the signature, offer, and subscriptionId in standard XML format
    verified_data = metadata | attested
    verified_data["offer"] = offer_urn

    xml_data = f"<document>{json.dumps(verified_data)}</document>"
    return xml_data
