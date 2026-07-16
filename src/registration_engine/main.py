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

"""Main entrypoint and event loop execution for the Registration Engine."""

import importlib
import random
import time

from cloudregister.registerutils import get_config

from registration_engine.connection import get_preferred_ip
from registration_engine.provider import detect_cloud_provider
from registration_engine.smt import get_target_update_server
from registration_engine.storage import determine_environment
from registration_engine.utils import get_logger

log = get_logger()

BASE_INTERVAL = 64800
JITTER_WINDOW = 3600


def run_one_cycle() -> None:
    """Run one full cycle of the registration verification workflow."""
    # 1. Cloud Provider Detection
    provider = detect_cloud_provider()
    log.info(
        "Cloud provider '%s' detected. Loading verification module.",
        provider,
    )

    # 2. Dynamic Module Loading & Verification Data Collection
    try:
        provider_module_name = f"registration_engine.{provider}"
        provider_module = importlib.import_module(provider_module_name)
    except ModuleNotFoundError as e:
        log.error(
            "Verification module for provider '%s' not found: %s",
            provider,
            e,
        )
        return
    except Exception as e:
        log.error(
            "Failed to load verification module for provider '%s': %s",
            provider,
            e,
        )
        return

    try:
        get_verification_data_func = getattr(provider_module, "get_verification_data")
    except AttributeError:
        log.error(
            "Module %s does not implement 'get_verification_data'.",
            provider_module_name,
        )
        return

    try:
        verification_xml = get_verification_data_func()
    except Exception as e:
        log.error(
            "%s verification data collection failed: %s",
            provider.capitalize(),
            e,
        )
        return

    log.info(
        "Verification data successfully generated for provider '%s' "
        "(length: %d characters).",
        provider,
        len(verification_xml),
    )

    # 3. Configuration Loading
    try:
        cfg = get_config()
    except Exception as e:
        log.error("Failed to load regionserverclnt config: %s", e)
        return

    # 4. SMT Server Discovery & Validation
    try:
        target_smt = get_target_update_server(cfg)
        if not target_smt:
            log.error("Failed to resolve responding SMT server.")
            return
    except Exception as e:
        log.error("SMT Discovery failed: %s", e)
        return

    # 5. Runtime Environment Detection & State Persistence
    try:
        ipv4 = target_smt.get("ipv4", "")
        ipv6 = target_smt.get("ipv6", "")
        cert = target_smt.get("cert", "")

        # Run Happy Eyeballs race to find the preferred routing IP
        registration_ip = get_preferred_ip(ipv6, ipv4)
        if not registration_ip:
            log.error(
                "Happy Eyeballs connection failed to resolve a preferred IP "
                "from SMT IPv4 (%s) and IPv6 (%s). Aborting state update.",
                ipv4,
                ipv6,
            )
            return

        log.info("Selected preferred registration IP: %s", registration_ip)

        # Dynamically determine storage backend/environment
        env = determine_environment()
        log.info(
            "Storage backend discovered: '%s'. Loading storage module.",
            env,
        )

        try:
            storage_module_name = f"registration_engine.{env}"
            storage_module = importlib.import_module(storage_module_name)
        except ModuleNotFoundError as e:
            log.error(
                "Storage module for environment '%s' not found: %s",
                env,
                e,
            )
            return
        except Exception as e:
            log.error(
                "Failed to load storage module for environment '%s': %s",
                env,
                e,
            )
            return

        try:
            update_func = getattr(storage_module, "update_registration_data")
        except AttributeError:
            log.error(
                "Storage module %s does not implement 'update_registration_data'.",
                storage_module_name,
            )
            return

        update_func(registration_ip, cert, verification_xml)
        log.info("State persistence successful. Registration data updated.")
    except Exception as e:
        log.error("Failed to persist state: %s", e)
        return


def main() -> None:
    """Main function executing the 18-hour registration loop."""
    log.info("Starting Rancher PAYG Registration Engine event loop (PID 1).")

    while True:
        try:
            run_one_cycle()
        except Exception as e:
            log.critical("Unhandled exception in loop cycle: %s", e)

        # Calculate random jitter for the next cycle
        jitter = random.randint(-JITTER_WINDOW, JITTER_WINDOW)
        sleep_duration = BASE_INTERVAL + jitter

        log.info(
            "Cycle complete. Scheduling next execution in %d seconds "
            "(approximately %.2f hours).",
            sleep_duration,
            sleep_duration / 3600.0,
        )

        try:
            time.sleep(sleep_duration)
        except KeyboardInterrupt:
            log.info("Event loop interrupted by user. Exiting.")
            break


if __name__ == "__main__":
    main()
