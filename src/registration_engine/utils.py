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

"""Utility functions for the Registration Engine."""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler


class RegistrationFormatter(logging.Formatter):
    """Custom logging Formatter that handles dynamic attributes.

    Specifically handles 'newline' and 'provider' attributes in the
    format string.
    """

    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "newline"):
            record.newline = "\n"
        if not hasattr(record, "provider"):
            record.provider = "unknown"
        return super().format(record)


def get_logger(debug: bool = False) -> logging.Logger:
    """Retrieve and configure the 'registration-engine' logger.

    Args:
        debug: If True, sets level to DEBUG. Otherwise, INFO.

    Returns:
        Configured logging.Logger instance.
    """
    logger = logging.getLogger("registration-engine")

    # If already configured, just update level and return
    # to avoid duplicate handlers.
    level = logging.DEBUG if debug else logging.INFO
    logger.setLevel(level)

    if not logger.handlers:
        log_path = os.path.expanduser("~/registration_engine.log")
        try:
            file_handler = RotatingFileHandler(
                log_path, maxBytes=10 * 1024 * 1024, backupCount=5
            )
        except Exception:
            # Fallback to local directory if ~ is not writable
            file_handler = RotatingFileHandler(
                "registration_engine.log",
                maxBytes=10 * 1024 * 1024,
                backupCount=5,
            )

        fmt = (
            "%(levelname)s %(asctime)s %(name)s:%(provider)s%(newline)s    %(message)s"
        )
        formatter = RegistrationFormatter(fmt)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    return logger
