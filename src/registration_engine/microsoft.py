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

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests
from azure.core.exceptions import AzureError
from azure.identity import WorkloadIdentityCredential

from registration_engine.utils import get_logger

ARM_ENDPOINT = "https://management.azure.com"
ARM_SCOPE = "https://management.azure.com/.default"
EXT_API_VERSION = "2023-05-01"

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


def _build_credential() -> WorkloadIdentityCredential:
    """
    Use WorkloadIdentityCredential.

    Fail if environement variables are missing.

    Returns:
        A WorkloadIdentityCredential instance with the token info.
    """
    return WorkloadIdentityCredential(
        tenant_id=_require_env("AZURE_TENANT_ID"),
        client_id=_require_env("AZURE_CLIENT_ID"),
        token_file_path=_require_env("AZURE_FEDERATED_TOKEN_FILE"),
    )


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
    credential: WorkloadIdentityCredential, extension_resource_id: str
) -> Plan:
    """Fetch extension plan block using ARM Identity.

    Retries with exponential backoff on transient (5xx, 429, network) errors.
    Non-retryable HTTP errors (401/403/404) fail-closed immediately.

    Args:
        credential: Azure Management Bearer token
        extension_resource_id: Resource ID of the extension

    Returns:
        Plan dictionary
    """
    url = f"{ARM_ENDPOINT}{extension_resource_id}?api-version={EXT_API_VERSION}"

    last_err: Optional[Exception] = None
    delay = 1.0
    for attempt in range(1, VERIFY_RETRY_MAX + 1):
        try:
            try:
                token = credential.get_token(ARM_SCOPE).token
            except AzureError as ae:
                last_err = ae
                raise ae

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
        except (requests.RequestException, AzureError) as e:
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


def get_latest_api_version() -> str:
    """Query IMDS versions endpoint for the latest API string.

    Returns:
        Latest API version string
    """
    pass


def get_compute_metadata() -> Dict[str, Any]:
    """Query compute IMDS and extract subscriptionId.

    Returns:
        Metadata dictionary containing subscriptionId
    """
    pass


def generate_nonce(offer: str) -> str:
    """Hash authoritative plan block and return a URL-safe Base64 encoded nonce

    Args:
        offer: Authoritative plan URN

    Returns:
        32-character SHA-3-256 base64 encoded nonce string
    """
    pass


def get_attested_data(nonce: str, api_version: str) -> Dict[str, Any]:
    """Query attested endpoint using the nonce and API version.

    Args:
        nonce: Cryptographic nonce
        api_version: IMDS API version

    Returns:
        Dictionary containing pkcs7 signature, subscription ID and
        plain text nonce
    """
    pass


def verify_once() -> Plan:
    """
    Perform one verification round. Returns the authoritative Plan or raises.

    Returns:
        Plan object with the authoritive plan information.
    """
    extension_resource_id = _require_env("EXTENSION_RESOURCE_ID")
    env_plan = Plan.from_env()
    credential = _build_credential()

    authoritative = fetch_extension_plan(credential, extension_resource_id)

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


def get_verification_data(offer: str) -> str:
    """
    Retrieve the attested data with the authoritive plan information
    for workload verification.

    Args:
        offer: Offer URN

    Returns:
        An xml formatted verification string.
    """
    pass
