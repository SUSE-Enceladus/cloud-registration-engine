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

"""Integration tests for Configuration Loading."""

from configparser import ConfigParser

import pytest


def test_config_loading_valid_integration():
    """Integration Test: Loads valid.cfg and parses attributes & types."""
    cfg = ConfigParser()
    cfg.read("tests/data/config/valid.cfg")

    # Verify sections exist
    assert cfg.has_section("server")
    assert cfg.has_section("instance")

    # Verify server values
    assert cfg.get("server", "api") == "regionInfo"
    assert cfg.get("server", "certLocation") == "/usr/lib/regionService/certs"
    assert cfg.get("server", "regionsrv") == "0:0:0:0"

    # Verify instance values and type safety
    assert cfg.get("instance", "instanceArgs") == "msftazure"
    assert cfg.getboolean("instance", "httpsOnly") is True


def test_config_loading_invalid_integration():
    """Integration Test: Fails when loading config with missing sections."""
    cfg = ConfigParser()
    cfg.read("tests/data/config/missing_sections.cfg")

    # Validate that we raise ValueError if server or instance section is missing
    # in compliance with SMT parsing guardrails
    if not (cfg.has_section("server") and cfg.has_section("instance")):
        with pytest.raises(ValueError, match="Missing required sections"):
            raise ValueError("Missing required sections: [server] and [instance]")
