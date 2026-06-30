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

from typing import Any, Dict, List, Optional
from lxml import etree
from configparser import RawConfigParser

from cloudregister.smt import SMT


def get_update_servers(
    region_smt_data: etree,
    cfg: configparser.RawConfigParser
) -> List[SMT]:
    """Return available update servers in a list.

    Args:
        region_smt_data: LXML tree with a list of SMT server data
        cfg: Cloud region server config object

    Returns:
        A list of SMT server instances
    """
    pass


def get_responding_update_server(
    region_smt_servers: List[SMT],
) -> Optional[SMT]:
    """Return the first active, responding SMT server from the list.

    Args:
        region_smt_servers: List of SMT server instances

    Returns:
        The first responding SMT instance, or None
    """
    pass


def get_target_update_server(
    cfg: configparser.RawConfigParser
) -> dict[str, str]:
    """Returns the IP and cert for the first responding SMT server.

    Args:
        cfg: configparser.RawConfigParser

    Returns:
        The first a dictionary with region server IP and cert
    """
    pass
