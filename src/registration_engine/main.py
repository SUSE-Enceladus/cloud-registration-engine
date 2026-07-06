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

import random
import time

from cloudregister.registerutils import get_config

from registration_engine.connection import get_preferred_ip
from registration_engine.k8s import update_registration_secret
from registration_engine.microsoft import get_verification_data
from registration_engine.provider import detect_cloud_provider
from registration_engine.smt import get_target_update_server
from registration_engine.utils import get_logger

log = get_logger()

BASE_INTERVAL = 64800
JITTER_WINDOW = 3600


def run_one_cycle() -> None:
    """Run one full cycle of the registration verification workflow."""
    # 1. Cloud Provider Detection
    provider = detect_cloud_provider()
    if provider != "microsoft":
        log.warning(
            "Host environment '%s' is not supported in this iteration. "
            "Only Microsoft Azure is supported. Skipping cycle.",
            provider
        )
        return

    log.info(
        "Microsoft Azure environment detected. "
        "Initiating verification cycle."
    )

    # 2. Microsoft AD Workload Identity & Metadata Collection
    try:
        verification_xml = get_verification_data()
    except Exception as e:
        log.error(
            "Microsoft AD Workload Identity or Metadata Collection "
            "failed: %s",
            e
        )
        return

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

    # 5. Kubernetes State Persistence
    try:
        ipv4 = target_smt.get("ipv4", "")
        ipv6 = target_smt.get("ipv6", "")
        cert = target_smt.get("cert", "")

        # Run Happy Eyeballs race to find the preferred routing IP
        registration_ip = get_preferred_ip(ipv6, ipv4)
        if not registration_ip:
            log.error(
                "Happy Eyeballs connection failed to resolve a preferred IP "
                "from SMT IPv4 (%s) and IPv6 (%s). Aborting secret update.",
                ipv4,
                ipv6
            )
            return

        log.info("Selected preferred registration IP: %s", registration_ip)
        update_registration_secret(registration_ip, cert, verification_xml)
        log.info("State persistence successful. Registration secret updated.")
    except Exception as e:
        log.error("Failed to persist state in Kubernetes secret: %s", e)
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
            sleep_duration / 3600.0
        )

        try:
            time.sleep(sleep_duration)
        except KeyboardInterrupt:
            log.info("Event loop interrupted by user. Exiting.")
            break


if __name__ == "__main__":
    main()
