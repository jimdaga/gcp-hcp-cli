"""Unit tests for hypershift utilities."""

import os
import pytest
from unittest.mock import patch, MagicMock

from gcphcp.utils.hypershift import (
    HypershiftError,
    get_hypershift_binary,
    check_hypershift_installed,
    validate_wif_config,
    wif_config_to_cluster_spec,
)


class TestGetHypershiftBinary:
    """Tests for get_hypershift_binary function."""

    def test_get_hypershift_binary_from_env(self, tmp_path):
        """When HYPERSHIFT_BINARY env is set it should return that path."""
        binary_path = tmp_path / "hypershift"
        binary_path.touch()

        with patch.dict(os.environ, {"HYPERSHIFT_BINARY": str(binary_path)}):
            result = get_hypershift_binary()

        assert result == str(binary_path)

    def test_get_hypershift_binary_env_not_file(self, tmp_path):
        """When HYPERSHIFT_BINARY points to non-file it should check config."""
        with patch.dict(os.environ, {"HYPERSHIFT_BINARY": "/nonexistent/path"}):
            with patch("shutil.which", return_value=None):
                result = get_hypershift_binary()

        assert result is None

    def test_get_hypershift_binary_from_config(self, tmp_path):
        """When config has hypershift_binary it should return that path."""
        binary_path = tmp_path / "hypershift"
        binary_path.touch()

        mock_config = MagicMock()
        mock_config.get_hypershift_binary.return_value = str(binary_path)

        with patch.dict(os.environ, {}, clear=True):
            # Clear HYPERSHIFT_BINARY if set
            os.environ.pop("HYPERSHIFT_BINARY", None)
            result = get_hypershift_binary(config=mock_config)

        assert result == str(binary_path)

    def test_get_hypershift_binary_from_path(self):
        """When hypershift is in PATH it should return that path."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("HYPERSHIFT_BINARY", None)
            with patch("shutil.which", return_value="/usr/local/bin/hypershift"):
                result = get_hypershift_binary()

        assert result == "/usr/local/bin/hypershift"

    def test_get_hypershift_binary_not_found(self):
        """When hypershift is not found it should return None."""
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("HYPERSHIFT_BINARY", None)
            with patch("shutil.which", return_value=None):
                result = get_hypershift_binary()

        assert result is None


class TestCheckHypershiftInstalled:
    """Tests for check_hypershift_installed function."""

    def test_check_hypershift_installed_true(self):
        """When hypershift is found it should return True."""
        with patch(
            "gcphcp.utils.hypershift.get_hypershift_binary",
            return_value="/usr/local/bin/hypershift",
        ):
            assert check_hypershift_installed() is True

    def test_check_hypershift_installed_false(self):
        """When hypershift is not found it should return False."""
        with patch("gcphcp.utils.hypershift.get_hypershift_binary", return_value=None):
            assert check_hypershift_installed() is False


class TestValidateWifConfig:
    """Tests for validate_wif_config function."""

    def test_validate_wif_config_valid(self):
        """When WIF config has all required fields it should return True."""
        valid_config = {
            "projectId": "my-project",
            "projectNumber": "123456789",
            "infraId": "my-infra",
            "workloadIdentityPool": {
                "poolId": "my-pool",
                "providerId": "my-provider",
            },
            "serviceAccounts": {
                "ctrlplane-op": "sa1@example.com",
                "nodepool-mgmt": "sa2@example.com",
            },
        }

        assert validate_wif_config(valid_config) is True

    def test_validate_wif_config_missing_project_id(self):
        """When WIF config is missing projectId it should return False."""
        invalid_config = {
            "projectNumber": "123456789",
            "infraId": "my-infra",
            "workloadIdentityPool": {
                "poolId": "my-pool",
                "providerId": "my-provider",
            },
            "serviceAccounts": {
                "ctrlplane-op": "sa1@example.com",
                "nodepool-mgmt": "sa2@example.com",
            },
        }

        assert validate_wif_config(invalid_config) is False

    def test_validate_wif_config_missing_pool_id(self):
        """When WIF config is missing poolId it should return False."""
        invalid_config = {
            "projectId": "my-project",
            "projectNumber": "123456789",
            "infraId": "my-infra",
            "workloadIdentityPool": {
                "providerId": "my-provider",
            },
            "serviceAccounts": {
                "ctrlplane-op": "sa1@example.com",
                "nodepool-mgmt": "sa2@example.com",
            },
        }

        assert validate_wif_config(invalid_config) is False

    def test_validate_wif_config_missing_service_account(self):
        """When WIF config is missing service account it should return False."""
        invalid_config = {
            "projectId": "my-project",
            "projectNumber": "123456789",
            "infraId": "my-infra",
            "workloadIdentityPool": {
                "poolId": "my-pool",
                "providerId": "my-provider",
            },
            "serviceAccounts": {
                "ctrlplane-op": "sa1@example.com",
                # Missing nodepool-mgmt
            },
        }

        assert validate_wif_config(invalid_config) is False

    def test_validate_wif_config_empty(self):
        """When WIF config is empty it should return False."""
        assert validate_wif_config({}) is False


class TestWifConfigToClusterSpec:
    """Tests for wif_config_to_cluster_spec function."""

    def test_wif_config_to_cluster_spec_conversion(self):
        """When converting WIF config it should produce correct cluster spec."""
        wif_config = {
            "projectId": "my-project",
            "projectNumber": "123456789",
            "infraId": "my-infra",
            "workloadIdentityPool": {
                "poolId": "my-pool",
                "providerId": "my-provider",
            },
            "serviceAccounts": {
                "ctrlplane-op": "ctrlplane@example.com",
                "nodepool-mgmt": "nodepool@example.com",
            },
        }

        result = wif_config_to_cluster_spec(wif_config)

        assert result["projectNumber"] == "123456789"
        assert result["poolID"] == "my-pool"
        assert result["providerID"] == "my-provider"
        ctrl_email = result["serviceAccountsRef"]["controlPlaneEmail"]
        assert ctrl_email == "ctrlplane@example.com"
        assert result["serviceAccountsRef"]["nodePoolEmail"] == "nodepool@example.com"

    def test_wif_config_to_cluster_spec_empty_config(self):
        """When converting empty config it should return None values."""
        result = wif_config_to_cluster_spec({})

        assert result["projectNumber"] is None
        assert result["poolID"] is None
        assert result["providerID"] is None


class TestHypershiftError:
    """Tests for HypershiftError exception."""

    def test_hypershift_error_message(self):
        """When raising HypershiftError it should contain the message."""
        with pytest.raises(HypershiftError) as exc_info:
            raise HypershiftError("Test error message")

        assert "Test error message" in str(exc_info.value)
