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

from registration_engine.utils import get_logger


def test_get_logger_config():
    """Test get_logger configuration and level changes."""
    # Patch home directory expansion so it doesn't write to real home
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_home = os.path.join(tmpdir, "home")
        os.makedirs(fake_home)

        log_file = os.path.join(fake_home, "registration_engine.log")
        with patch("os.path.expanduser", return_value=log_file):
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


@patch("registration_engine.utils.RotatingFileHandler")
def test_get_logger_unwritable_directory(mock_rotating_handler):
    """Test get_logger handles RotatingFileHandler failures gracefully."""
    mock_rotating_handler.side_effect = PermissionError("Permission denied")

    logger = logging.getLogger("registration-engine")
    logger.handlers.clear()

    log_instance = get_logger(debug=False)
    assert log_instance.level == logging.INFO
    # Only StreamHandler should be present as file_handler creation failed
    assert len(log_instance.handlers) == 1
    assert isinstance(log_instance.handlers[0], logging.StreamHandler)
