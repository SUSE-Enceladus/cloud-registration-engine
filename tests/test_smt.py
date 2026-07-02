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

"""Chaos and resilience tests for the SMT discovery module."""

import sys
from unittest.mock import MagicMock

# 1. Dynamically mock the cloudregister SLES packages in sys.modules
mock_smt_class = MagicMock()
mock_smt_module = MagicMock()
mock_smt_module.SMT = mock_smt_class

mock_reg_utils_module = MagicMock()
mock_reg_utils_module.https_only = MagicMock(return_value=True)
mock_reg_utils_module.store_smt_data = MagicMock()
mock_reg_utils_module.get_state_dir = MagicMock(return_value="/tmp")
mock_reg_utils_module.set_as_current_smt = MagicMock()
mock_reg_utils_module.fetch_smt_data = MagicMock()

mock_defaults_module = MagicMock()
mock_defaults_module.AVAILABLE_SMT_SERVER_DATA_FILE_NAME = "smt_%d.json"

sys.modules["cloudregister"] = MagicMock()
sys.modules["cloudregister.smt"] = mock_smt_module
sys.modules["cloudregister.registerutils"] = mock_reg_utils_module
sys.modules["cloudregister.defaults"] = mock_defaults_module

# 2. Now we can safely import registration_engine.smt module
from registration_engine.smt import (  # noqa: E402
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


def test_get_update_servers_cache_failure_chaos():
    """Chaos Test: Disk/cache write failure does not crash discovery."""
    cfg = MagicMock()
    # Simulate list of 1 child node in xml
    child = MagicMock()
    region_smt_data = [child]

    # Mock SMT instantiation to return mock server
    mock_smt_instance = MagicMock()
    mock_smt_class.return_value = mock_smt_instance

    # Force store_smt_data to raise OSError (e.g. Disk Full, Access Denied)
    mock_reg_utils_module.store_smt_data.side_effect = OSError("Disk full")

    result = get_update_servers(region_smt_data, cfg)

    # Discovery should succeed and return the server despite cache crash
    assert len(result) == 1
    assert result[0] == mock_smt_instance
    mock_reg_utils_module.store_smt_data.assert_called_once()

    # Reset mock state
    mock_reg_utils_module.store_smt_data.side_effect = None


def test_get_responding_update_server_loop_exception_chaos():
    """Chaos Test: Individual server check failures do not abort loop."""
    # Create two mock servers
    srv1 = MagicMock()
    # First server raises exception during responsiveness check
    srv1.is_responsive.side_effect = Exception("DNS Resolution Timeout")
    srv1.get_ipv4.return_value = "10.0.0.1"
    srv1.get_ipv6.return_value = "::1"

    srv2 = MagicMock()
    # Second server is responsive and healthy
    srv2.is_responsive.return_value = True
    srv2.get_ipv4.return_value = "10.0.0.2"
    srv2.get_ipv6.return_value = "::2"

    result = get_responding_update_server([srv1, srv2])

    # Should skip the broken srv1, continue loop, and find srv2
    assert result == srv2
    mock_reg_utils_module.set_as_current_smt.assert_called_with(srv2)


def test_get_target_update_server_return_type_and_outage_chaos():
    """Chaos Test: Outages return None and success conforms to dict type."""
    cfg = MagicMock()

    # Case A: fetch_smt_data raises transient network error
    mock_reg_utils_module.fetch_smt_data.side_effect = Exception("Down")
    assert get_target_update_server(cfg) is None
    mock_reg_utils_module.fetch_smt_data.side_effect = None

    # Case B: No SMT server responds
    mock_reg_utils_module.fetch_smt_data.return_value = []
    assert get_target_update_server(cfg) is None

    # Case C: Success returns dictionary format
    srv = MagicMock()
    srv.is_responsive.return_value = True
    srv.get_ipv4.return_value = "192.168.1.100"
    srv.get_ipv6.return_value = "::1"
    srv.get_cert.return_value = "pem-data"
    mock_smt_class.return_value = srv

    # Mock XML data returning one node
    mock_reg_utils_module.fetch_smt_data.return_value = [MagicMock()]

    res = get_target_update_server(cfg)
    assert isinstance(res, dict)
    assert res["ipv4"] == "192.168.1.100"
    assert res["ipv6"] == "::1"
    assert res["cert"] == "pem-data"
