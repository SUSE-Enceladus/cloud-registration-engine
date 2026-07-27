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

"""Resilience tests for SMT discovery using the real cloudregister library."""

from unittest.mock import MagicMock, patch

from cloudregister.smt import SMT
from lxml import etree

from registration_engine.smt import (
    get_responding_update_server,
    get_target_update_server,
    get_update_servers,
)


def test_get_update_servers_null_data_chaos():
    """Chaos Test: Verify empty/null etree data does not crash loop."""
    cfg = MagicMock()
    # Call with None region_smt_data
    result = get_update_servers(None, cfg)
    assert result == []


@patch("registration_engine.smt.store_smt_data")
def test_get_update_servers_cache_failure_chaos(mock_store_smt_data):
    """Chaos Test: Disk/cache write failure does not crash discovery."""
    cfg = MagicMock()

    # Create a real SMT XML element node
    child = etree.Element(
        "SMTServer",
        SMTserverIP="192.168.1.100",
        SMTserverIPv6="::1",
        SMTserverName="smt.example.com",
        fingerprint="AB:CD:EF",
    )
    region_smt_data = [child]

    # Force store_smt_data to raise OSError (e.g. Disk Full, Access Denied)
    mock_store_smt_data.side_effect = OSError("Disk full")

    result = get_update_servers(region_smt_data, cfg)

    # Discovery should succeed and return the server despite cache crash
    assert len(result) == 1
    assert isinstance(result[0], SMT)
    assert result[0].get_ipv4() == "192.168.1.100"
    mock_store_smt_data.assert_called_once()


@patch("registration_engine.smt.set_as_current_smt")
def test_get_responding_update_server_loop_exception_chaos(mock_set_as_current_smt):
    """Chaos Test: Individual server check failures do not abort loop."""
    node1 = etree.Element(
        "SMTServer",
        SMTserverIP="10.0.0.1",
        SMTserverIPv6="::1",
        SMTserverName="smt1.example.com",
        fingerprint="AB:CD:EF",
    )
    node2 = etree.Element(
        "SMTServer",
        SMTserverIP="10.0.0.2",
        SMTserverIPv6="::2",
        SMTserverName="smt2.example.com",
        fingerprint="CD:EF:AB",
    )

    srv1 = SMT(node1)
    srv2 = SMT(node2)

    with patch.object(SMT, "is_responsive") as mock_is_responsive:
        # First server raises exception during responsiveness check.
        # Second server is fully responsive.
        mock_is_responsive.side_effect = [Exception("DNS Resolution Timeout"), True]

        result = get_responding_update_server([srv1, srv2])

        # Should skip the broken srv1, continue loop, and find srv2
        assert result == srv2
        mock_set_as_current_smt.assert_called_with(srv2)


@patch("registration_engine.smt.fetch_smt_data")
@patch("registration_engine.smt.set_as_current_smt")
def test_get_target_update_server_return_type_and_outage_chaos(
    mock_set_as_current_smt, mock_fetch_smt_data
):
    """Chaos Test: Outages return None and success conforms to dict type."""
    cfg = MagicMock()

    # Case A: fetch_smt_data raises transient network error
    mock_fetch_smt_data.side_effect = Exception("Down")
    assert get_target_update_server(cfg) is None

    # Case B: No SMT server responds
    mock_fetch_smt_data.side_effect = None
    mock_fetch_smt_data.return_value = []
    assert get_target_update_server(cfg) is None

    # Case C: Success returns dictionary format
    node = etree.Element(
        "SMTServer",
        SMTserverIP="192.168.1.100",
        SMTserverIPv6="::1",
        SMTserverName="smt.example.com",
        fingerprint="AB:CD:EF",
    )
    mock_fetch_smt_data.return_value = [node]

    with (
        patch.object(SMT, "is_responsive", return_value=True),
        patch.object(SMT, "get_cert", return_value="pem-data"),
    ):
        res = get_target_update_server(cfg)
        assert isinstance(res, dict)
        assert res["ipv4"] == "192.168.1.100"
        assert res["ipv6"] == "::1"
        assert res["cert"] == "pem-data"
