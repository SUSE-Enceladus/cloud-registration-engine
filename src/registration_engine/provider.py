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

"""Cloud Provider Detection module."""

import socket
import subprocess
import urllib.error
import urllib.request

from registration_engine.utils import get_logger

logger = get_logger()

PROVIDER_MICROSOFT = "microsoft"
PROVIDER_AMAZON = "amazon"
PROVIDER_GOOGLE = "google"
PROVIDER_UNKNOWN = "unknown"


def check_imds_endpoint(
    url: str, headers: dict[str, str] = None, method: str = "GET", timeout: int = 2
) -> bool:
    """Utility function to make an HTTP request with a timeout.

    Args:
        url: URL of IMDS endpoint
        headers: Any headers to include with the request
        method: HTTP method to use
        timeout: How long to wait for response in seconds

    Returns:
        True if the imds endpoint is responsive.
    """
    if headers is None:
        headers = {}
    try:
        req = urllib.request.Request(url, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return response.status == 200, body
    except (urllib.error.URLError, socket.timeout, UnicodeDecodeError):
        return False, ""


def detect_cloud_provider() -> str:
    """Determine the host environment through sequential fallback mechanism.

    Returns:
        "microsoft", "amazon", "google", or "unknown".
    """
    logger.info("Attempting IMDS detection...")
    if check_azure_imds():
        logger.info(
            "Detected Microsoft Azure IMDS.", extra={"provider": PROVIDER_MICROSOFT}
        )
        return PROVIDER_MICROSOFT
    if check_gcp_imds():
        logger.info(
            "Detected Google Cloud Platform IMDS.", extra={"provider": PROVIDER_GOOGLE}
        )
        return PROVIDER_GOOGLE
    if check_aws_imds():
        logger.info(
            "Detected Amazon Web Services IMDS.", extra={"provider": PROVIDER_AMAZON}
        )
        return PROVIDER_AMAZON

    logger.info("IMDS unreachable or timed out. Falling back to hardware info...")

    dmi_file_check = check_dmi_files()
    if dmi_file_check:
        logger.info(
            "Detected provider via DMI files: %s",
            dmi_file_check,
            extra={"provider": dmi_file_check},
        )
        return dmi_file_check

    dmidecode_check = check_dmidecode()
    if dmidecode_check:
        logger.info(
            "Detected provider via dmidecode: %s",
            dmidecode_check,
            extra={"provider": dmidecode_check},
        )
        return dmidecode_check

    logger.info(
        "Cloud provider detection failed. Unknown provider.",
        extra={"provider": PROVIDER_UNKNOWN},
    )
    return PROVIDER_UNKNOWN


def check_azure_imds() -> bool:
    """Check Azure IMDS endpoint (IPv4 and IPv4-mapped IPv6).

    Returns:
        True if running on Azure, False otherwise.
    """
    endpoints = ["169.254.169.254", "[::ffff:169.254.169.254]"]
    headers = {"Metadata": "true"}

    for ip in endpoints:
        url = f"http://{ip}/metadata/instance?api-version=2021-02-01"
        success, _ = check_imds_endpoint(url, headers=headers)
        if success:
            return True

    return False


def check_gcp_imds() -> bool:
    """Check GCP IMDS endpoint (DNS first for native IPv6 routing, then IPs).

    Returns:
        True if running on GCP, False otherwise.
    """
    endpoints = [
        "metadata.google.internal",
        "169.254.169.254",
        "[::ffff:169.254.169.254]",
    ]
    headers = {"Metadata-Flavor": "Google"}

    for target in endpoints:
        url = f"http://{target}/computeMetadata/v1/"
        success, _ = check_imds_endpoint(url, headers=headers)
        if success:
            return True

    return False


def check_aws_imds() -> bool:
    """Check AWS IMDS endpoint across IPv4 and native IPv6.

    Returns:
        True if running on AWS, False otherwise.
    """
    endpoints = ["169.254.169.254", "[fd00:ec2::254]"]
    token_headers = {"X-aws-ec2-metadata-token-ttl-seconds": "60"}

    for ip in endpoints:
        # 1. Try IMDSv2 first by requesting a token via PUT
        token_url = f"http://{ip}/latest/api/token"
        token_success, token = check_imds_endpoint(
            token_url, headers=token_headers, method="PUT"
        )

        if token_success and token:
            # 2. If token is retrieved, use it to query metadata
            metadata_url = f"http://{ip}/latest/meta-data/"
            metadata_headers = {"X-aws-ec2-metadata-token": token}
            success, _ = check_imds_endpoint(metadata_url, headers=metadata_headers)
            if success:
                return True

        # 3. Fallback to IMDSv1 if token request failed
        url = f"http://{ip}/latest/meta-data/"
        success, _ = check_imds_endpoint(url)
        if success:
            return True

    return False


def check_dmi_files() -> bool:
    """Check DMI files under /sys/class/dmi/id/ for cloud provider information.

    Returns:
        True if information is successfully determined, False otherwise.
    """
    dmi_files = [
        "/sys/class/dmi/id/sys_vendor",
        "/sys/class/dmi/id/product_name",
        "/sys/class/dmi/id/chassis_asset_tag",
    ]

    for file_path in dmi_files:
        try:
            with open(file_path, "r") as f:
                content = f.read().strip().lower()
                if "microsoft" in content or "azure" in content:
                    return PROVIDER_MICROSOFT
                elif "amazon" in content or "ec2" in content:
                    return PROVIDER_AMAZON
                elif "google" in content:
                    return PROVIDER_GOOGLE
        except OSError:
            continue

    return None


def check_dmidecode() -> bool:
    """Check cloud provider via system dmidecode command.

    Returns:
        True if information is successfully determined, False otherwise.
    """
    try:
        result = subprocess.run(
            ["dmidecode", "-s", "system-manufacturer"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        if result.returncode == 0:
            manufacturer = result.stdout.decode("utf-8").strip().lower()
            if "microsoft" in manufacturer or "azure" in manufacturer:
                return PROVIDER_MICROSOFT
            elif "amazon" in manufacturer or "ec2" in manufacturer:
                return PROVIDER_AMAZON
            elif "google" in manufacturer:
                return PROVIDER_GOOGLE
    except (FileNotFoundError, subprocess.SubprocessError):
        # The dmidecode binary is not installed, or command timed out/failed
        pass
    return None
