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

"""Centralized pytest configuration and global sys.modules mocking."""

import sys
from unittest.mock import MagicMock

import pytest

# 1. Define global mock instances
global_smt_class = MagicMock()
global_smt_module = MagicMock()
global_smt_module.SMT = global_smt_class

global_reg_utils_module = MagicMock()
global_reg_utils_module.https_only = MagicMock(return_value=True)
global_reg_utils_module.store_smt_data = MagicMock()
global_reg_utils_module.get_state_dir = MagicMock(return_value="/tmp")
global_reg_utils_module.set_as_current_smt = MagicMock()
global_reg_utils_module.fetch_smt_data = MagicMock()
global_reg_utils_module.get_config = MagicMock()

global_defaults_module = MagicMock()
global_defaults_module.AVAILABLE_SMT_SERVER_DATA_FILE_NAME = "smt_%d.json"

# 2. Inject globally into sys.modules
sys.modules["cloudregister"] = MagicMock()
sys.modules["cloudregister.smt"] = global_smt_module
sys.modules["cloudregister.registerutils"] = global_reg_utils_module
sys.modules["cloudregister.defaults"] = global_defaults_module


@pytest.fixture(autouse=True)
def reset_global_mocks():
    """Automatically reset global mocks call history and side-effects."""
    global_smt_class.reset_mock(side_effect=True, return_value=True)
    global_smt_module.reset_mock(side_effect=True, return_value=True)
    global_reg_utils_module.reset_mock(side_effect=True, return_value=True)
    global_defaults_module.reset_mock(side_effect=True, return_value=True)

    # Re-establish basic defaults
    global_smt_module.SMT = global_smt_class
    global_reg_utils_module.https_only.return_value = True
    global_reg_utils_module.get_state_dir.return_value = "/tmp"
    global_defaults_module.AVAILABLE_SMT_SERVER_DATA_FILE_NAME = "smt_%d.json"


@pytest.fixture
def mock_smt_class():
    """Pytest fixture to provide global mock_smt_class to tests."""
    return global_smt_class


@pytest.fixture
def mock_reg_utils_module():
    """Pytest fixture to provide global mock_reg_utils_module to tests."""
    return global_reg_utils_module
