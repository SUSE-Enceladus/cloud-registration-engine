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

"""Unit tests for the utils/logging module."""

import logging
import os
import tempfile
from unittest.mock import patch
from registration_engine.utils import get_logger, RegistrationFormatter


def test_registration_formatter():
    """Test that the custom formatter correctly injects default attributes."""
    formatter = RegistrationFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=10,
        msg="test message",
        args=(),
        exc_info=None
    )
    # By default, record shouldn't have 'newline' or 'provider' attributes
    assert not hasattr(record, 'newline')
    assert not hasattr(record, 'provider')

    # Formatting should inject default values
    formatter.format(record)
    assert record.newline == '\n'
    assert record.provider == 'unknown'


def test_get_logger_config():
    """Test get_logger configuration and level changes."""
    # Patch home directory expansion so it doesn't write to real home
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_home = os.path.join(tmpdir, "home")
        os.makedirs(fake_home)

        log_file = os.path.join(fake_home, "registration_engine.log")
        with patch('os.path.expanduser', return_value=log_file):
            # Clear handlers from any previous test runs to ensure fully run
            logger = logging.getLogger("registration-engine")
            logger.handlers.clear()

            # 1. Test standard logger
            log_instance = get_logger(debug=False)
            assert log_instance.level == logging.INFO
            assert len(log_instance.handlers) == 2

            # 2. Test debug logger update
            log_instance_debug = get_logger(debug=True)
            assert log_instance_debug.level == logging.DEBUG
            # Should not duplicate handler
            assert len(log_instance_debug.handlers) == 2
