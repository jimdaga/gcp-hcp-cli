"""Configuration management for GCP HCP CLI."""

import logging
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

logger = logging.getLogger(__name__)


class Config:
    """Configuration manager for GCP HCP CLI."""

    def __init__(self, config_path: Path) -> None:
        """Initialize configuration manager.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = config_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from file."""
        if not self.config_path.exists():
            logger.debug(f"Configuration file does not exist: {self.config_path}")
            return

        try:
            with open(self.config_path, "r") as f:
                self._data = yaml.safe_load(f) or {}
            logger.debug(f"Loaded configuration from {self.config_path}")
        except Exception as e:
            logger.warning(f"Failed to load configuration from {self.config_path}: {e}")
            self._data = {}

    def save(self) -> None:
        """Save configuration to file."""
        try:
            # Ensure directory exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, "w") as f:
                yaml.safe_dump(self._data, f, default_flow_style=False, sort_keys=True)

            logger.debug(f"Saved configuration to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save configuration to {self.config_path}: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value.

        Args:
            key: Configuration key (supports dot notation)
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        value = self._data
        for part in key.split("."):
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return default
        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value.

        Args:
            key: Configuration key (supports dot notation)
            value: Value to set
        """
        data = self._data
        parts = key.split(".")

        # Navigate to the parent of the target key
        for part in parts[:-1]:
            if part not in data:
                data[part] = {}
            data = data[part]

        # Set the final key
        data[parts[-1]] = value

    def unset(self, key: str) -> None:
        """Remove configuration value.

        Args:
            key: Configuration key to remove
        """
        data = self._data
        parts = key.split(".")

        # Navigate to the parent of the target key
        for part in parts[:-1]:
            if part not in data:
                return  # Key doesn't exist
            data = data[part]

        # Remove the final key
        if parts[-1] in data:
            del data[parts[-1]]

    def get_all(self) -> Dict[str, Any]:
        """Get all configuration values.

        Returns:
            Dictionary of all configuration values
        """
        return self._data.copy()

    def get_api_endpoint(self) -> str:
        """Get API endpoint URL.

        Returns:
            API endpoint URL
        """
        return self.get("api_endpoint", "https://api.gcphcp.example.com")

    def get_credentials_path(self) -> Path:
        """Get path to credentials file.

        Returns:
            Path to credentials file
        """
        credentials_path = self.get("credentials_path")
        if credentials_path:
            return Path(credentials_path)
        return Path.home() / ".gcphcp" / "credentials.json"

    def get_client_secrets_path(self) -> Optional[Path]:
        """Get path to OAuth client secrets file.

        Returns:
            Path to client secrets file or None if not configured
        """
        secrets_path = self.get("client_secrets_path")
        if secrets_path:
            return Path(secrets_path)
        return None

    def get_default_project(self) -> Optional[str]:
        """Get default project ID.

        Returns:
            Default project ID or None if not configured
        """
        return self.get("default_project")

    def get_audience(self) -> Optional[str]:
        """Get JWT audience for identity tokens.

        Returns:
            JWT audience or None if not configured
        """
        return self.get("audience")

    def get_version(self) -> str:
        """Get CLI version.

        Returns:
            CLI version string
        """
        # Import here to avoid circular imports
        from .. import __version__

        return __version__
