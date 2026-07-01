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

"""SMT Server Discovery & Validation module."""

import os
from typing import List, Optional
from lxml import etree
from configparser import RawConfigParser

from registration_engine.utils import get_logger

from cloudregister.smt import SMT
from cloudregister.registerutils import (
    https_only,
    store_smt_data,
    get_state_dir,
    set_as_current_smt,
    fetch_smt_data
)
from cloudregister.defaults import (
    AVAILABLE_SMT_SERVER_DATA_FILE_NAME
)

log = get_logger()


def get_update_servers(
    region_smt_data: etree,
    cfg: RawConfigParser
) -> List[SMT]:
    """Return available update servers in a list.

    Args:
        region_smt_data: LXML tree with a list of SMT server data
        cfg: Cloud region server config object

    Returns:
        A list of SMT server instances
    """
    if region_smt_data is None:
        log.warning("No SMT data provided (region_smt_data is None).")
        return []

    region_smt_servers = []
    use_https_only = https_only(cfg)

    for count, child in enumerate(region_smt_data, start=1):
        smt_server = SMT(child, use_https_only)
        region_smt_servers.append(smt_server)
        # Write available servers to cache, protecting against write errors
        try:
            store_smt_data(
                os.path.join(
                    get_state_dir(),
                    AVAILABLE_SMT_SERVER_DATA_FILE_NAME % count
                ),
                smt_server,
            )
        except Exception as e:
            log.warning(
                "Failed to store SMT server %d to state cache: %s",
                count,
                e
            )

    return region_smt_servers


def get_responding_update_server(
    region_smt_servers: List[SMT],
) -> Optional[SMT]:
    """Return the first active, responding SMT server from the list.

    Args:
        region_smt_servers: List of SMT server instances

    Returns:
        The first responding SMT instance, or None
    """
    if not region_smt_servers:
        log.warning("No SMT update servers available to check.")
        return None

    tested_smt_servers = []

    for smt_srv in region_smt_servers:
        try:
            tested_smt_servers.append(
                (smt_srv.get_ipv4(), smt_srv.get_ipv6())
            )
            if smt_srv.is_responsive():
                set_as_current_smt(smt_srv)
                return smt_srv
        except Exception as e:
            log.warning(
                "Error checking responsiveness on SMT server: %s",
                e
            )

    log.error(
        'No response from: %s',
        format(tested_smt_servers)
    )
    return None


def get_target_update_server(
    cfg: RawConfigParser
) -> Optional[dict[str, str]]:
    """Returns the IP and cert for the first responding SMT server.

    Args:
        cfg: RawConfigParser

    Returns:
        A dictionary with region server IP and cert, or None if not found
    """
    try:
        region_smt_data = fetch_smt_data(cfg, None, True)
    except Exception as e:
        log.error("Failed to fetch SMT server data: %s", e)
        return None

    region_smt_servers = get_update_servers(region_smt_data, cfg)
    responding_server = get_responding_update_server(region_smt_servers)

    if not responding_server:
        log.warning("No responding SMT update server located.")
        return None

    log.info(
        'Responding update server located: %s / %s',
        responding_server.get_ipv4(),
        responding_server.get_ipv6()
    )

    try:
        return {
            "ipv4": responding_server.get_ipv4(),
            "ipv6": responding_server.get_ipv6(),
            "cert": responding_server.get_cert()
        }
    except Exception as e:
        log.error("Failed to extract IP/cert from responding SMT: %s", e)
        return None
