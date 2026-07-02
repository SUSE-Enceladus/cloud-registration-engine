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

"""Unit tests for the application main event loop."""

from unittest.mock import MagicMock, patch

from registration_engine.main import main, run_one_cycle
from registration_engine.microsoft import Plan


@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.verify_once")
def test_run_one_cycle_not_microsoft_skipped(mock_verify, mock_detect):
    """Test that non-Microsoft providers skip rest of loop."""
    mock_detect.return_value = "amazon"

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_verify.assert_not_called()


@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.verify_once")
@patch("registration_engine.main.get_verification_data")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
@patch("registration_engine.main.get_preferred_ip")
@patch("registration_engine.main.update_registration_secret")
def test_run_one_cycle_microsoft_success(
    mock_k8s, mock_preferred, mock_smt, mock_config, mock_xml, mock_verify, mock_detect
):
    """Test full sequential workflow success on Microsoft Azure."""
    mock_detect.return_value = "microsoft"
    mock_verify.return_value = Plan("pub", "off", "pl")
    mock_xml.return_value = "<xml>verification</xml>"
    mock_config.return_value = MagicMock()
    mock_smt.return_value = {
        "ipv4": "10.0.0.5",
        "ipv6": "2001:db8::1",
        "cert": "pem-cert"
    }
    mock_preferred.return_value = "10.0.0.5"

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_verify.assert_called_once()
    mock_xml.assert_called_once_with("pub:off:pl")
    mock_config.assert_called_once()
    mock_smt.assert_called_once()
    mock_preferred.assert_called_once_with("2001:db8::1", "10.0.0.5")
    mock_k8s.assert_called_once_with(
        "10.0.0.5", "pem-cert", "<xml>verification</xml>"
    )


@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.verify_once")
@patch("registration_engine.main.get_verification_data")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
@patch("registration_engine.main.get_preferred_ip")
@patch("registration_engine.main.update_registration_secret")
def test_run_one_cycle_preferred_ip_failed(
    mock_k8s, mock_preferred, mock_smt, mock_config, mock_xml, mock_verify, mock_detect
):
    """Test workflow returns early if Happy Eyeballs connection fails."""
    mock_detect.return_value = "microsoft"
    mock_verify.return_value = Plan("pub", "off", "pl")
    mock_xml.return_value = "<xml>verification</xml>"
    mock_config.return_value = MagicMock()
    mock_smt.return_value = {
        "ipv4": "10.0.0.5",
        "ipv6": "2001:db8::1",
        "cert": "pem-cert"
    }
    # Both IPs fail connection
    mock_preferred.return_value = None

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_verify.assert_called_once()
    mock_preferred.assert_called_once_with("2001:db8::1", "10.0.0.5")
    # Kubernetes secret update must NOT be called
    mock_k8s.assert_not_called()


@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.verify_once")
@patch("registration_engine.main.get_config")
def test_run_one_cycle_verification_failed(mock_config, mock_verify, mock_detect):
    """Test graceful abort on verification failures."""
    mock_detect.return_value = "microsoft"
    mock_verify.side_effect = RuntimeError("TAMPERED")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_verify.assert_called_once()
    mock_config.assert_not_called()


@patch("registration_engine.main.time.sleep")
@patch("registration_engine.main.run_one_cycle")
def test_main_loop_exit_on_keyboard_interrupt(mock_cycle, mock_sleep):
    """Test main infinite loop terminates cleanly on KeyboardInterrupt."""
    mock_sleep.side_effect = KeyboardInterrupt()

    main()

    mock_cycle.assert_called_once()
    mock_sleep.assert_called_once()
