"""
============================================================================
FILE: config.py
LOCATION: server/config.py
============================================================================
PURPOSE:
    Centralized environment configuration management for the A2UI backend.
    Loads settings from .env and provides a Settings class with OpenRouter
    and application configuration values.
ROLE IN PROJECT:
    Single source of truth for all environment-based configuration.
    - Loads .env at import time via load_dotenv()
    - Exposes a singleton settings instance used across the server
KEY COMPONENTS:
    - Settings: Class containing OPENROUTER_BASE_URL and application config
    - settings: Singleton instance for application-wide configuration access
DEPENDENCIES:
    - External: python-dotenv
    - Internal: server.database.storage_mode
USAGE:
    ```python
    from server.config import settings
    print(settings.OPENROUTER_BASE_URL)
    ```
============================================================================
"""

import os

from dotenv import load_dotenv

from server.database.storage_mode import DeploymentMode

# Load environment variables from .env file
load_dotenv()


class Settings:
    """Environment-backed server settings."""

    def __init__(self) -> None:
        raw_mode = os.getenv("DEPLOYMENT_MODE", "local").strip().lower()
        try:
            self.deployment_mode = DeploymentMode(raw_mode)
        except ValueError as exc:
            raise RuntimeError(
                "DEPLOYMENT_MODE must be local or cloud"
            ) from exc
        self.mongo_uri = os.getenv("MONGO_URI") or None
        self.mongo_db = os.getenv("MONGO_DB") or None
        self.OPENROUTER_BASE_URL = os.getenv(
            "OPENROUTER_BASE_URL",
            "https://openrouter.ai/api/v1",
        )
        self.OPENROUTER_TIMEOUT_SECONDS = float(
            os.getenv("OPENROUTER_TIMEOUT_SECONDS", "60.0")
        )
        self.GENERALCOMPUTE_BASE_URL = os.getenv(
            "GENERALCOMPUTE_BASE_URL",
            "https://api.generalcompute.com/v1",
        )
        self.GENERALCOMPUTE_TIMEOUT_SECONDS = float(
            os.getenv("GENERALCOMPUTE_TIMEOUT_SECONDS", "60.0")
        )


settings = Settings()
