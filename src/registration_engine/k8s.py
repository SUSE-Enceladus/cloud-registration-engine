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

"""Kubernetes State Persistence module."""

import json
import os
import time

from kubernetes import client, config

from registration_engine.utils import get_logger

logger = get_logger()

K8S_RETRY_MAX = int(os.getenv("K8S_RETRY_MAX", "5"))
K8S_RETRY_BACKOFF = float(os.getenv("K8S_RETRY_BACKOFF", "2.0"))


def update_registration_secret(
    registration_ip: str,
    cert: str,
    instance_data: str | dict
) -> None:
    """Store/patch compiled registration info back into K8s secret.

    Args:
        registration_ip: Active SMT routing IP address
        cert: Validated SMT certificate string
        instance_data: String or dictionary of collected instance data
    """
    secret_name = os.getenv("REGISTRATION_SECRET_NAME", "scc-registration")
    namespace = os.getenv(
        "REGISTRATION_SECRET_NAMESPACE", "cattle-scc-system"
    )

    # Initialize kubernetes configuration
    try:
        config.load_incluster_config()
    except Exception:
        try:
            config.load_kube_config()
        except Exception as e:
            logger.error("Failed to load Kubernetes configuration: %s", e)
            raise e

    v1 = client.CoreV1Api()

    reg_code = os.getenv(
        "REGISTRATION_CODE",
        os.getenv("REG_CODE", os.getenv("REGCODE", ""))
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
        "registrationUrlCert": cert
    }

    body = client.V1Secret(
        metadata=client.V1ObjectMeta(name=secret_name),
        string_data=string_data
    )

    last_err = None
    delay = 1.0
    for attempt in range(1, K8S_RETRY_MAX + 1):
        try:
            # Check if secret exists first
            v1.read_namespaced_secret(name=secret_name, namespace=namespace)
            v1.patch_namespaced_secret(
                name=secret_name,
                namespace=namespace,
                body=body
            )
            logger.info(
                "Successfully patched secret %s in namespace %s",
                secret_name,
                namespace
            )
            return
        except client.exceptions.ApiException as error:
            if error.status == 404:
                try:
                    body.type = "Opaque"
                    v1.create_namespaced_secret(
                        namespace=namespace,
                        body=body
                    )
                    logger.info(
                        "Successfully created secret %s in namespace %s",
                        secret_name,
                        namespace
                    )
                    return
                except client.exceptions.ApiException as ce:
                    if ce.status in (409, 429, 500, 502, 503, 504):
                        last_err = ce
                    else:
                        raise ce
            elif error.status in (409, 429, 500, 502, 503, 504):
                last_err = error
            else:
                logger.error(
                    "Failed to access secret %s in namespace %s: %s",
                    secret_name,
                    namespace,
                    error
                )
                raise error
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

    raise RuntimeError(
        f"Kubernetes secret update exhausted retries: {last_err}"
    )
