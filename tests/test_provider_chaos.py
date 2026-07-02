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

"""Chaos and resilience tests for the provider module."""

import subprocess
from unittest.mock import MagicMock, patch

from registration_engine import provider


@patch("registration_engine.provider.urllib.request.urlopen")
def test_check_imds_endpoint_unicode_decode_chaos(mock_urlopen):
    """Chaos Test: Verify malformed non-UTF-8 responses don't crash loop."""
    mock_response = MagicMock()
    mock_response.status = 200
    # Provide raw binary bytes that cannot be decoded as valid UTF-8
    mock_response.read.return_value = b"\xff\xfe\x00\x00_invalid_utf8"
    mock_response.__enter__.return_value = mock_response
    mock_urlopen.return_value = mock_response

    # Should handle decoding failure gracefully and return False
    success, body = provider.check_imds_endpoint("http://fake-url")
    assert success is False
    assert body == ""


@patch("registration_engine.provider.subprocess.run")
def test_check_dmidecode_timeout_chaos(mock_run):
    """Chaos Test: Verify that hanging dmidecode subprocess is handled."""
    # Simulate a subprocess TimeoutExpired exception
    mock_run.side_effect = subprocess.TimeoutExpired(cmd=["dmidecode"], timeout=5)

    # Should handle timeout gracefully and return None (fallback failed)
    assert provider.check_dmidecode() is None


@patch("builtins.open", side_effect=PermissionError("SELinux Access Denied"))
def test_check_dmi_files_permission_chaos(mock_open_file):
    """Chaos Test: Verify read permission errors are handled."""
    # Should handle PermissionError gracefully and return None.
    assert provider.check_dmi_files() is None
