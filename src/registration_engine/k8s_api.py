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


"""Shared Kubernetes REST API helpers: retry handling and ConfigMap access."""

import os
import time
from collections.abc import Callable

import requests

from registration_engine.utils import get_logger

logger = get_logger()

K8S_RETRY_MAX = int(os.getenv("K8S_RETRY_MAX", "5"))
K8S_RETRY_BACKOFF = float(os.getenv("K8S_RETRY_BACKOFF", "2.0"))
TRANSIENT_STATUS_CODES = (409, 429, 500, 502, 503, 504)
REQUEST_TIMEOUT = 10


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


def configmap_url(base_url: str, namespace: str, name: str) -> str:
    """Return the API URL of a ConfigMap."""
    return f"{base_url}/api/v1/namespaces/{namespace}/configmaps/{name}"


def get_configmap_data(
    url: str, headers: dict, verify: str | bool, allow_missing: bool = False
) -> dict | None:
    """Return the ``data`` of a ConfigMap, or None if missing and allowed."""
    response = requests.get(
        url, headers=headers, verify=verify, timeout=REQUEST_TIMEOUT
    )
    if allow_missing and response.status_code == 404:
        return None
    _check_response(response, "read")
    return response.json().get("data") or {}


def merge_patch(
    url: str, payload: dict, headers: dict, verify: str | bool, action: str = "patch"
) -> None:
    """Send a JSON merge-patch and check the response."""
    response = requests.patch(
        url,
        headers=headers | {"Content-Type": "application/merge-patch+json"},
        json=payload,
        verify=verify,
        timeout=REQUEST_TIMEOUT,
    )
    _check_response(response, action)
