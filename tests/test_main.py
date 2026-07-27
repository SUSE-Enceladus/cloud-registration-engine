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


@patch("registration_engine.microsoft.get_verification_data")
@patch("registration_engine.main.detect_cloud_provider")
def test_run_one_cycle_not_microsoft_skipped(mock_detect, mock_xml):
    """Test that non-Microsoft providers skip rest of loop."""
    mock_detect.return_value = "amazon"

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_xml.assert_not_called()


@patch("registration_engine.main.log")
@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.microsoft.get_verification_data")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
@patch("registration_engine.main.get_preferred_ip")
@patch("registration_engine.k8s.update_registration_data")
def test_run_one_cycle_microsoft_success(
    mock_k8s,
    mock_preferred,
    mock_smt,
    mock_config,
    mock_xml,
    mock_detect,
    mock_determine_env,
    mock_log,
):
    """Test full sequential workflow success on Microsoft Azure."""
    mock_detect.return_value = "microsoft"
    mock_determine_env.return_value = "k8s"
    mock_xml.return_value = "<xml>verification</xml>"
    mock_config.return_value = MagicMock()
    mock_smt.return_value = {
        "ipv4": "10.0.0.5",
        "ipv6": "2001:db8::1",
        "cert": "pem-cert",
    }
    mock_preferred.return_value = "10.0.0.5"

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_determine_env.assert_called_once()
    mock_xml.assert_called_once_with()
    mock_config.assert_called_once()
    mock_smt.assert_called_once()
    mock_preferred.assert_called_once_with("2001:db8::1", "10.0.0.5")
    mock_k8s.assert_called_once_with("10.0.0.5", "pem-cert", "<xml>verification</xml>")
    mock_log.info.assert_any_call(
        "Verification data successfully generated for provider '%s' "
        "(length: %d characters).",
        "microsoft",
        23,
    )
    mock_log.info.assert_any_call(
        "Storage backend discovered: '%s'. Loading storage module.",
        "k8s",
    )


@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.microsoft.get_verification_data")
@patch("registration_engine.main.get_config")
def test_run_one_cycle_get_verification_data_failed(
    mock_config, mock_xml, mock_detect, mock_determine_env
):
    """Test graceful abort on verification failures."""
    mock_detect.return_value = "microsoft"
    mock_xml.side_effect = RuntimeError("TAMPERED")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_xml.assert_called_once_with()
    mock_config.assert_not_called()
    mock_determine_env.assert_not_called()


@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.microsoft.get_verification_data")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
@patch("registration_engine.main.get_preferred_ip")
@patch("registration_engine.k8s.update_registration_data")
def test_run_one_cycle_preferred_ip_failed(
    mock_k8s,
    mock_preferred,
    mock_smt,
    mock_config,
    mock_xml,
    mock_detect,
    mock_determine_env,
):
    """Test workflow returns early if Happy Eyeballs connection fails."""
    mock_detect.return_value = "microsoft"
    mock_determine_env.return_value = "k8s"
    mock_xml.return_value = "<xml>verification</xml>"
    mock_config.return_value = MagicMock()
    mock_smt.return_value = {
        "ipv4": "10.0.0.5",
        "ipv6": "2001:db8::1",
        "cert": "pem-cert",
    }
    # Both IPs fail connection
    mock_preferred.return_value = None

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_xml.assert_called_once_with()
    mock_preferred.assert_called_once_with("2001:db8::1", "10.0.0.5")
    # Kubernetes secret update must NOT be called
    mock_k8s.assert_not_called()


@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.microsoft.get_verification_data")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
@patch("registration_engine.main.get_preferred_ip")
@patch("registration_engine.k8s.update_registration_data")
def test_run_one_cycle_unsupported_storage_env(
    mock_k8s,
    mock_preferred,
    mock_smt,
    mock_config,
    mock_xml,
    mock_detect,
    mock_determine_env,
):
    """Test workflow skips persistence if storage environment is not k8s."""
    mock_detect.return_value = "microsoft"
    mock_determine_env.return_value = "local"
    mock_xml.return_value = "<xml>verification</xml>"

    mock_config.return_value = MagicMock()
    mock_smt.return_value = {
        "ipv4": "10.0.0.5",
        "ipv6": "2001:db8::1",
        "cert": "pem-cert",
    }
    mock_preferred.return_value = "10.0.0.5"

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_determine_env.assert_called_once()
    # Kubernetes secret update must NOT be called since env is local
    mock_k8s.assert_not_called()


@patch("registration_engine.main.time.sleep")
@patch("registration_engine.main.run_one_cycle")
def test_main_loop_exit_on_keyboard_interrupt(mock_cycle, mock_sleep):
    """Test main infinite loop terminates cleanly on KeyboardInterrupt."""
    mock_sleep.side_effect = KeyboardInterrupt()

    main()

    mock_cycle.assert_called_once()
    mock_sleep.assert_called_once()


@patch("registration_engine.main.importlib.import_module")
@patch("registration_engine.main.detect_cloud_provider")
def test_run_one_cycle_provider_module_not_found(mock_detect, mock_import_module):
    """Test that run_one_cycle handles missing provider module gracefully."""
    mock_detect.return_value = "microsoft"
    mock_import_module.side_effect = ModuleNotFoundError("No microsoft module")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_import_module.assert_called_once_with("registration_engine.microsoft")


@patch("registration_engine.main.importlib.import_module")
@patch("registration_engine.main.detect_cloud_provider")
def test_run_one_cycle_provider_module_generic_exception(
    mock_detect, mock_import_module
):
    """Test that run_one_cycle handles generic load exceptions gracefully."""
    mock_detect.return_value = "microsoft"
    mock_import_module.side_effect = RuntimeError("SyntaxError or similar")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_import_module.assert_called_once_with("registration_engine.microsoft")


@patch("registration_engine.main.importlib.import_module")
@patch("registration_engine.main.detect_cloud_provider")
def test_run_one_cycle_provider_module_missing_function(
    mock_detect, mock_import_module
):
    """Test run_one_cycle fails if provider module lacks get_verification_data."""
    mock_detect.return_value = "microsoft"
    mock_module = MagicMock(spec=[])  # Empty spec, lacks get_verification_data
    mock_import_module.return_value = mock_module

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_import_module.assert_called_once_with("registration_engine.microsoft")


@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.importlib.import_module")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.get_config")
def test_run_one_cycle_get_config_failed(
    mock_config, mock_detect, mock_import_module, mock_determine_env
):
    """Test that run_one_cycle fails gracefully when get_config fails."""
    mock_detect.return_value = "microsoft"
    mock_determine_env.return_value = "k8s"

    mock_module = MagicMock()
    mock_module.get_verification_data.return_value = "<xml></xml>"
    mock_import_module.return_value = mock_module

    mock_config.side_effect = RuntimeError("Failed to read config file")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_config.assert_called_once()


@patch("registration_engine.main.determine_environment")
@patch("registration_engine.main.importlib.import_module")
@patch("registration_engine.main.detect_cloud_provider")
@patch("registration_engine.main.get_config")
@patch("registration_engine.main.get_target_update_server")
def test_run_one_cycle_smt_discovery_failed(
    mock_smt, mock_config, mock_detect, mock_import_module, mock_determine_env
):
    """Test that run_one_cycle fails gracefully when SMT discovery fails."""
    mock_detect.return_value = "microsoft"
    mock_determine_env.return_value = "k8s"

    mock_module = MagicMock()
    mock_module.get_verification_data.return_value = "<xml></xml>"
    mock_import_module.return_value = mock_module

    mock_config.return_value = MagicMock()
    mock_smt.side_effect = RuntimeError("SMT Error")

    run_one_cycle()

    mock_detect.assert_called_once()
    mock_config.assert_called_once()
    mock_smt.assert_called_once()


@patch("registration_engine.main.time.sleep")
@patch("registration_engine.main.run_one_cycle")
def test_main_unhandled_exception_logged(mock_cycle, mock_sleep):
    """Test main loop logs critical error on unhandled exceptions and sleeps."""
    # First cycle raises Exception, second cycle raises KeyboardInterrupt to exit loop
    mock_cycle.side_effect = [Exception("Unexpected system crash"), None]
    mock_sleep.side_effect = [None, KeyboardInterrupt()]

    main()

    assert mock_cycle.call_count == 2
    assert mock_sleep.call_count == 2
