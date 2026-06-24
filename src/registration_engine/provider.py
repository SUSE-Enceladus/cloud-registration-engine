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


def check_imds_endpoint(
    url: str,
    headers: dict[str, str] = None,
    method: str = 'GET',
    timeout: int = 2
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
    pass


def detect_cloud_provider() -> str:
    """Determine the host environment through sequential fallback mechanism.

    Returns:
        "microsoft", "amazon", "google", or "unknown".
    """
    pass


def check_azure_imds() -> bool:
    """Check Azure Instance Metadata Service.

    Returns:
        True if running on Azure, False otherwise.
    """
    pass


def check_gcp_imds() -> bool:
    """Check GCP Instance Metadata Service.

    Returns:
        True if running on GCP, False otherwise.
    """
    pass


def check_aws_imds() -> bool:
    """Check AWS Instance Metadata Service (IMDSv2 with fallback to IMDSv1).

    Returns:
        True if running on AWS, False otherwise.
    """
    pass


def check_dmi_files() -> bool:
    """Check DMI files under /sys/class/dmi/id/ for cloud provider information.

    Returns:
        True if information is successfully determined, False otherwise.
    """
    pass


def check_dmidecode() -> bool:
    """Check cloud provider via system dmidecode command.

    Returns:
        True if information is successfully determined, False otherwise.
    """
    pass
