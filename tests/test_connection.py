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

"""Unit and chaos tests for the Happy Eyeballs connection module."""

import socket
from unittest.mock import MagicMock, patch

from registration_engine.connection import (
    get_preferred_ip,
)
from registration_engine.connection import (
    test_connection as conn_attempt,
)


@patch("registration_engine.connection.socket.socket")
@patch("registration_engine.connection.time.sleep")
def test_connection_ipv6_wins(mock_sleep, mock_socket_class):
    """Happy Path: IPv6 is responsive and wins immediately."""
    mock_sock = MagicMock()
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    res = get_preferred_ip("2001:db8::1", "192.168.1.1")
    assert res == "2001:db8::1"


@patch("registration_engine.connection.socket.socket")
@patch("registration_engine.connection.time.sleep")
def test_connection_ipv4_fallback_wins(mock_sleep, mock_socket_class):
    """Test fallback: IPv6 is down/timed out, and IPv4 wins."""
    mock_sock_v6 = MagicMock()
    mock_sock_v6.connect.side_effect = socket.timeout("Connect timed out")

    mock_sock_v4 = MagicMock()

    mock_socket_class.return_value.__enter__.side_effect = [mock_sock_v6, mock_sock_v4]

    res = get_preferred_ip("2001:db8::1", "192.168.1.1")
    assert res == "192.168.1.1"


@patch("registration_engine.connection.socket.socket")
@patch("registration_engine.connection.time.sleep")
def test_connection_both_fail_chaos(mock_sleep, mock_socket_class):
    """Chaos Test: Complete network outage where both families fail."""
    mock_sock = MagicMock()
    mock_sock.connect.side_effect = OSError("Network unreachable")
    mock_socket_class.return_value.__enter__.return_value = mock_sock

    res = get_preferred_ip("2001:db8::1", "192.168.1.1")
    assert res is None


@patch("registration_engine.connection.socket.socket")
@patch("registration_engine.connection.time.sleep")
def test_connection_aborted_early_if_winner_exists(mock_sleep, mock_socket_class):
    """Test connection is aborted early if another thread already won."""
    winner = ["2001:db8::1"]

    conn_attempt("192.168.1.1", 443, socket.AF_INET, 0.25, winner)

    mock_socket_class.assert_not_called()
