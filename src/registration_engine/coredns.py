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


"""CoreDNS record management for the registration FQDN.

On Azure AKS the ``coredns`` ConfigMap is reconciled by AKS and manual edits
are reverted, so the record is written to the ``coredns-custom`` ConfigMap
instead. Keys ending in ``.override`` there are imported into the default
server block. On every other provider the ``coredns`` Corefile is patched.
"""

import re
from collections.abc import Callable
from datetime import datetime, timezone

from registration_engine.k8s_api import (
    _run_with_retry,
    configmap_url,
    get_configmap_data,
    merge_patch,
)
from registration_engine.provider import PROVIDER_MICROSOFT, PROVIDER_UNKNOWN
from registration_engine.utils import get_logger

logger = get_logger()

COREDNS_NAMESPACE = "kube-system"
COREDNS_CONFIGMAP = "coredns"
COREDNS_KEY = "Corefile"
COREDNS_DEPLOYMENT = "coredns"
COREDNS_CUSTOM_CONFIGMAP = "coredns-custom"
COREDNS_CUSTOM_KEY = "registration.override"

INDENT = "    "


def _hosts_block(ip_address: str, fqdn: str, indent: str = "") -> str:
    """Return a new CoreDNS hosts block for a single record."""
    return (
        f"{indent}hosts {{\n"
        f"{indent}{INDENT}{ip_address} {fqdn}\n"
        f"{indent}{INDENT}fallthrough\n"
        f"{indent}}}"
    )


def _set_host_record(text: str, ip_address: str, fqdn: str) -> str | None:
    """Update the record in existing config text.

    Overwrites the line for the FQDN if there is one, otherwise adds the record
    to an existing ``hosts {`` block. Returns None if neither is possible.
    """
    fqdn_line = r"^([ \t]*)\S+[ \t]+" + re.escape(fqdn) + r"(?=\s|$).*$"
    if re.search(fqdn_line, text, flags=re.MULTILINE):
        return re.sub(
            fqdn_line,
            lambda m: f"{m.group(1)}{ip_address} {fqdn}",
            text,
            flags=re.MULTILINE,
        )

    hosts_open = r"^([ \t]*)hosts\s*\{"
    if re.search(hosts_open, text, flags=re.MULTILINE):
        return re.sub(
            hosts_open,
            lambda m: f"{m.group(0)}\n{m.group(1)}{INDENT}{ip_address} {fqdn}",
            text,
            count=1,
            flags=re.MULTILINE,
        )

    return None


def process_corefile(corefile: str, ip_address: str, fqdn: str) -> str:
    """Add or update the record in a full CoreDNS Corefile."""
    if not corefile or not corefile.strip():
        raise ValueError("Corefile is empty or invalid.")

    updated = _set_host_record(corefile, ip_address, fqdn)
    if updated is not None:
        return updated

    # No record and no hosts block: add one to the main server block.
    server_block = r"(\.:53\s*\{)"
    if re.search(server_block, corefile):
        block = _hosts_block(ip_address, fqdn, INDENT)
        return re.sub(
            server_block, lambda m: f"{m.group(1)}\n{block}", corefile, count=1
        )

    raise ValueError("Could not find standard server block (.:53 {) in Corefile.")


def process_custom_corefile(override: str, ip_address: str, fqdn: str) -> str:
    """Add or update the record in a coredns-custom ``.override`` snippet.

    The snippet holds bare directives that AKS imports into the default
    server block, so there is no ``.:53 {`` wrapper. Empty text is valid.
    """
    override = override or ""

    updated = _set_host_record(override, ip_address, fqdn)
    if updated is not None:
        return updated

    block = _hosts_block(ip_address, fqdn) + "\n"
    if override.strip():
        return override.rstrip("\n") + "\n" + block
    return block


def _update_configmap_key(
    url: str,
    key: str,
    transform: Callable[[str], str],
    headers: dict,
    verify: str | bool,
    allow_missing: bool = False,
) -> bool | None:
    """Read a ConfigMap key, transform it and patch it back only if it changed.

    Only the given key is written, so other keys are left untouched.

    Args:
        url: API URL of the ConfigMap.
        key: Key in the ConfigMap ``data`` to read and update.
        transform: Takes the current value ("" if the key is absent) and
            returns the new value.
        headers: Request headers including authorization.
        verify: TLS verification setting passed to requests.
        allow_missing: If True a missing ConfigMap (HTTP 404) is not an error.

    Returns:
        A three-state result, so callers must compare with ``None`` explicitly
        rather than rely on truthiness:

        - ``None``: the ConfigMap does not exist (only when allow_missing is set).
        - ``True``: the value changed and the key was written.
        - ``False``: the value was already up to date and nothing was written.
    """
    data = get_configmap_data(url, headers, verify, allow_missing)
    if data is None:
        return None

    current = data.get(key, "")
    updated = transform(current)
    if updated == current:
        return False

    merge_patch(url, {"data": {key: updated}}, headers, verify)
    return True


def _restart_coredns(base_url: str, headers: dict, verify: str | bool) -> None:
    """Trigger a rollout restart of the CoreDNS deployment."""
    url = (
        f"{base_url}/apis/apps/v1/namespaces/{COREDNS_NAMESPACE}"
        f"/deployments/{COREDNS_DEPLOYMENT}"
    )
    restarted_at = datetime.now(timezone.utc).isoformat()
    annotations = {"kubectl.kubernetes.io/restartedAt": restarted_at}
    payload = {"spec": {"template": {"metadata": {"annotations": annotations}}}}
    merge_patch(url, payload, headers, verify, action="restart")
    logger.info("Triggered rollout restart of CoreDNS deployment.")


def update_coredns_record(
    ip_address: str,
    fqdn: str,
    base_url: str,
    token: str,
    verify: str | bool,
    provider: str = PROVIDER_UNKNOWN,
) -> None:
    """Make the FQDN resolve to the IP address in the cluster's CoreDNS.

    On Azure (AKS) the existing coredns-custom ConfigMap is updated and CoreDNS
    is restarted if the record changed. coredns-custom is never created: if it
    is missing, or on any other provider, the coredns ConfigMap is patched.

    Transient failures (connection errors, timeouts, HTTP 409/429/5xx) retry the
    whole read-modify-write cycle so a conflict re-reads the latest ConfigMap.

    Raises:
        ValueError: The Corefile could not be processed (not retried).
        requests.HTTPError: Non-transient HTTP error (not retried).
        RuntimeError: All retries were exhausted.
    """
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    custom_url = configmap_url(base_url, COREDNS_NAMESPACE, COREDNS_CUSTOM_CONFIGMAP)
    core_url = configmap_url(base_url, COREDNS_NAMESPACE, COREDNS_CONFIGMAP)

    def attempt() -> None:
        if provider == PROVIDER_MICROSOFT:
            written = _update_configmap_key(
                custom_url,
                COREDNS_CUSTOM_KEY,
                lambda text: process_custom_corefile(text, ip_address, fqdn),
                headers,
                verify,
                allow_missing=True,
            )
            if written is not None:
                if written:
                    logger.info("Updated %s in %s.", fqdn, COREDNS_CUSTOM_CONFIGMAP)
                    _restart_coredns(base_url, headers, verify)
                return
            logger.info(
                "ConfigMap %s not found, falling back to %s.",
                COREDNS_CUSTOM_CONFIGMAP,
                COREDNS_CONFIGMAP,
            )

        _update_configmap_key(
            core_url,
            COREDNS_KEY,
            lambda text: process_corefile(text, ip_address, fqdn),
            headers,
            verify,
        )

    _run_with_retry(attempt, "CoreDNS update", fatal=(ValueError,))
