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

"""Centralized pytest configuration and real cloudregister setup."""

import shutil
import tempfile

import cloudregister.defaults
import cloudregister.registerutils
import pytest

# Create a temporary directory to act as the cloudregister state directory
# during the entire test suite run, avoiding permission issues with
# /var/cache/cloudregister
test_state_dir = tempfile.mkdtemp()

# Override the registration cache directory to point to our temporary directory
cloudregister.defaults.REGISTRATION_DATA_DIR = test_state_dir
cloudregister.registerutils.REGISTRATION_DATA_DIR = test_state_dir


@pytest.fixture(scope="session", autouse=True)
def cleanup_temp_dir():
    """Ensure the temporary registration state directory is cleaned up after testing."""
    yield
    shutil.rmtree(test_state_dir, ignore_errors=True)
