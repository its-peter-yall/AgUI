"""
============================================================================
FILE: safe_logging.py
LOCATION: server/utils/safe_logging.py
============================================================================
PURPOSE:
    Fixed-shape logging helper that records exception type only, never
    external exception text or traceback that may contain secrets.
ROLE IN PROJECT:
    Hardens generation failure paths against credential leakage into logs.
    - Supplements SearchSecretRedactionFilter for exception surfaces
    - Used by graph runner and detached runtime task callbacks
KEY COMPONENTS:
    - log_external_failure: Safe ERROR log without message or traceback
DEPENDENCIES:
    - External: logging
    - Internal: None
USAGE:
    log_external_failure(logger, event="generation_failed",
                         session_id=sid, error=exc)
============================================================================
"""

from __future__ import annotations

import logging


def log_external_failure(
    logger: logging.Logger,
    *,
    event: str,
    session_id: str,
    error: BaseException,
) -> None:
    """Log safe external-failure metadata without message or traceback."""
    logger.error(
        "%s session_id=%s error_type=%s",
        event,
        session_id,
        type(error).__name__,
    )
