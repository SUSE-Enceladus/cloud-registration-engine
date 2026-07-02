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

"""TCP Happy Eyeballs connection helper module."""

import socket
import threading
import time


def test_connection(ip: str, port: int, family: int, delay: float, winner: list):
    """Attempts a TCP socket connection after a specified delay."""
    if delay > 0:
        time.sleep(delay)

    # If the other protocol already won during our delay, abort early
    if winner:
        return

    try:
        # Create a TCP socket for the specific address family (IPv4 or IPv6)
        with socket.socket(family, socket.SOCK_STREAM) as sock:
            sock.settimeout(2.0)  # 2-second timeout per attempt
            sock.connect((ip, port))

            # The first successful connection appends its IP to the list
            if not winner:
                winner.append(ip)
    except (OSError, socket.timeout):
        pass  # Connection failed, timed out, or network unreachable


def get_preferred_ip(ipv6: str, ipv4: str, port: int = 443) -> str:
    """Runs the Happy Eyeballs race and returns the winning IP."""
    winner = []

    # Give IPv6 a 250ms head start (0.25 seconds)
    v6_thread = threading.Thread(
        target=test_connection,
        args=(ipv6, port, socket.AF_INET6, 0.0, winner),
    )
    v4_thread = threading.Thread(
        target=test_connection,
        args=(ipv4, port, socket.AF_INET, 0.25, winner),
    )

    v6_thread.start()
    v4_thread.start()

    v6_thread.join()
    v4_thread.join()

    return winner[0] if winner else None
