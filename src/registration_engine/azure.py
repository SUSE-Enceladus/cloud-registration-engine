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

"""Azure Workload Identity & Metadata Collection module."""

from typing import Any, Dict

from azure.identity import WorkloadIdentityCredential


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
    credential: WorkloadIdentityCredential,
    extension_resource_id: str
) -> Plan:
    """Fetch extension plan block using ARM Identity.

    Args:
        credential: Azure Management Bearer token
        extension_resource_id: Resource ID of the extension

    Returns:
        Plan dictionary
    """
    pass


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
    """Hash authoritative plan block and return a URL-safe Base64 encoded nonce.

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
    pass


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
