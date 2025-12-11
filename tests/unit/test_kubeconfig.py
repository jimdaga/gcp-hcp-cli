"""Unit tests for kubeconfig utilities."""

import pytest
from unittest.mock import patch, MagicMock
import subprocess
import yaml

from gcphcp.utils.kubeconfig import (
    KubeconfigError,
    get_oc_binary,
    check_oc_installed,
    login_with_oc,
    validate_token,
    update_kubeconfig,
    get_google_id_token,
    _decode_token_claims,
    _upsert_by_name,
)


class TestGetOcBinary:
    """Tests for get_oc_binary function."""

    def test_get_oc_binary_from_env_var(self):
        """When OC_BINARY env var is set it should return that path."""
        with patch.dict("os.environ", {"OC_BINARY": "/custom/path/oc"}):
            with patch("os.path.isfile", return_value=True):
                result = get_oc_binary()
        assert result == "/custom/path/oc"

    def test_get_oc_binary_from_env_var_invalid_path(self):
        """When OC_BINARY env var points to non-existent file it should fallback."""
        with patch.dict("os.environ", {"OC_BINARY": "/invalid/oc"}):
            with patch("os.path.isfile", return_value=False):
                with patch("shutil.which", return_value="/usr/local/bin/oc"):
                    result = get_oc_binary()
        assert result == "/usr/local/bin/oc"

    def test_get_oc_binary_from_config(self):
        """When config has oc_binary setting it should return that path."""
        mock_config = MagicMock()
        mock_config.get_oc_binary.return_value = "/config/path/oc"
        with patch.dict("os.environ", {}, clear=True):
            with patch("os.path.isfile", return_value=True):
                result = get_oc_binary(config=mock_config)
        assert result == "/config/path/oc"

    def test_get_oc_binary_from_path(self):
        """When oc is in PATH it should return the path."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("shutil.which", return_value="/usr/local/bin/oc"):
                result = get_oc_binary()
        assert result == "/usr/local/bin/oc"

    def test_get_oc_binary_not_found(self):
        """When oc is not found anywhere it should return None."""
        with patch.dict("os.environ", {}, clear=True):
            with patch("shutil.which", return_value=None):
                result = get_oc_binary()
        assert result is None

    def test_get_oc_binary_env_takes_priority(self):
        """When env var is set it should take priority over PATH."""
        with patch.dict("os.environ", {"OC_BINARY": "/env/oc"}):
            with patch("os.path.isfile", return_value=True):
                with patch("shutil.which", return_value="/path/oc"):
                    result = get_oc_binary()
        assert result == "/env/oc"


class TestCheckOcInstalled:
    """Tests for check_oc_installed function."""

    def test_check_oc_installed_true(self):
        """When oc is found it should return True."""
        with patch(
            "gcphcp.utils.kubeconfig.get_oc_binary",
            return_value="/usr/local/bin/oc",
        ):
            assert check_oc_installed() is True

    def test_check_oc_installed_false(self):
        """When oc is not found it should return False."""
        with patch("gcphcp.utils.kubeconfig.get_oc_binary", return_value=None):
            assert check_oc_installed() is False


class TestLoginWithOc:
    """Tests for login_with_oc function."""

    def test_login_with_oc_success(self):
        """When oc login succeeds it should return True and message."""
        with patch(
            "gcphcp.utils.kubeconfig.get_oc_binary",
            return_value="/usr/local/bin/oc",
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="Logged in as user",
                    stderr="",
                )
                success, message = login_with_oc(
                    server="https://api.example.com:443",
                    token="test-token",
                )
        assert success is True
        assert "Logged in" in message

    def test_login_with_oc_not_found(self):
        """When oc is not found it should raise KubeconfigError."""
        with patch("gcphcp.utils.kubeconfig.get_oc_binary", return_value=None):
            with pytest.raises(KubeconfigError) as exc_info:
                login_with_oc(
                    server="https://api.example.com:443",
                    token="test-token",
                )
        assert "oc CLI not found" in str(exc_info.value)

    def test_login_with_oc_failure(self):
        """When oc login fails it should raise KubeconfigError."""
        with patch(
            "gcphcp.utils.kubeconfig.get_oc_binary",
            return_value="/usr/local/bin/oc",
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Authentication failed",
                )
                with pytest.raises(KubeconfigError) as exc_info:
                    login_with_oc(
                        server="https://api.example.com:443",
                        token="test-token",
                    )
        assert "Authentication failed" in str(exc_info.value)

    def test_login_with_oc_timeout(self):
        """When oc login times out it should raise KubeconfigError."""
        with patch(
            "gcphcp.utils.kubeconfig.get_oc_binary",
            return_value="/usr/local/bin/oc",
        ):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = subprocess.TimeoutExpired(cmd="oc", timeout=30)
                with pytest.raises(KubeconfigError) as exc_info:
                    login_with_oc(
                        server="https://api.example.com:443",
                        token="test-token",
                    )
        assert "timed out" in str(exc_info.value)


class TestValidateToken:
    """Tests for validate_token function."""

    def test_validate_token_success(self):
        """When token is valid it should return user info."""
        # Create a mock JWT token with email claim
        import base64
        import json

        payload = {"email": "test@example.com", "hd": "example.com", "sub": "123"}
        encoded_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        mock_token = f"header.{encoded_payload}.signature"

        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=200, ok=True)
            result = validate_token(
                server="https://api.example.com:443",
                token=mock_token,
            )
        assert result["email"] == "test@example.com"
        assert result["hd"] == "example.com"

    def test_validate_token_401(self):
        """When token is invalid it should raise KubeconfigError."""
        with patch("requests.get") as mock_get:
            mock_get.return_value = MagicMock(status_code=401)
            with pytest.raises(KubeconfigError) as exc_info:
                validate_token(
                    server="https://api.example.com:443",
                    token="invalid-token",
                )
        assert "Invalid or expired token" in str(exc_info.value)

    def test_validate_token_connection_error(self):
        """When connection fails it should raise KubeconfigError."""
        import requests

        with patch("requests.get") as mock_get:
            mock_get.side_effect = requests.exceptions.ConnectionError()
            with pytest.raises(KubeconfigError) as exc_info:
                validate_token(
                    server="https://api.example.com:443",
                    token="test-token",
                )
        assert "Cannot reach" in str(exc_info.value)


class TestUpdateKubeconfig:
    """Tests for update_kubeconfig function."""

    def test_update_kubeconfig_new_file(self, tmp_path):
        """When kubeconfig doesn't exist it should create new file."""
        kubeconfig_path = tmp_path / "config"

        context_name = update_kubeconfig(
            cluster_name="test-cluster",
            server="https://api.example.com:443",
            token="test-token",
            kubeconfig_path=str(kubeconfig_path),
        )

        assert kubeconfig_path.exists()
        assert context_name == "default/test-cluster"

        with open(kubeconfig_path) as f:
            kc = yaml.safe_load(f)

        assert kc["current-context"] == "default/test-cluster"
        assert len(kc["clusters"]) == 1
        assert kc["clusters"][0]["name"] == "test-cluster"
        assert kc["clusters"][0]["cluster"]["server"] == "https://api.example.com:443"

    def test_update_kubeconfig_existing_file(self, tmp_path):
        """When kubeconfig exists it should merge entries."""
        kubeconfig_path = tmp_path / "config"

        # Create existing config
        existing = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [
                {"name": "existing-cluster", "cluster": {"server": "https://other.com"}}
            ],
            "users": [{"name": "existing-user", "user": {"token": "old-token"}}],
            "contexts": [],
            "current-context": "",
        }
        with open(kubeconfig_path, "w") as f:
            yaml.dump(existing, f)

        # Add new cluster
        update_kubeconfig(
            cluster_name="new-cluster",
            server="https://api.example.com:443",
            token="new-token",
            kubeconfig_path=str(kubeconfig_path),
        )

        with open(kubeconfig_path) as f:
            kc = yaml.safe_load(f)

        # Should have both clusters
        assert len(kc["clusters"]) == 2
        cluster_names = [c["name"] for c in kc["clusters"]]
        assert "existing-cluster" in cluster_names
        assert "new-cluster" in cluster_names

    def test_update_kubeconfig_upsert(self, tmp_path):
        """When cluster already exists it should update it."""
        kubeconfig_path = tmp_path / "config"

        # Create first entry
        update_kubeconfig(
            cluster_name="test-cluster",
            server="https://old.example.com:443",
            token="old-token",
            kubeconfig_path=str(kubeconfig_path),
        )

        # Update same cluster
        update_kubeconfig(
            cluster_name="test-cluster",
            server="https://new.example.com:443",
            token="new-token",
            kubeconfig_path=str(kubeconfig_path),
        )

        with open(kubeconfig_path) as f:
            kc = yaml.safe_load(f)

        # Should still have only one cluster
        assert len(kc["clusters"]) == 1
        assert kc["clusters"][0]["cluster"]["server"] == "https://new.example.com:443"


class TestGetGoogleIdToken:
    """Tests for get_google_id_token function."""

    def test_get_google_id_token_success(self):
        """When gcloud returns token it should return it."""
        with patch("shutil.which", return_value="/usr/bin/gcloud"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout="test-token-12345\n",
                    stderr="",
                )
                result = get_google_id_token()
        assert result == "test-token-12345"

    def test_get_google_id_token_gcloud_not_found(self):
        """When gcloud is not found it should raise KubeconfigError."""
        with patch("shutil.which", return_value=None):
            with pytest.raises(KubeconfigError) as exc_info:
                get_google_id_token()
        assert "gcloud CLI not found" in str(exc_info.value)

    def test_get_google_id_token_failure(self):
        """When gcloud fails it should raise KubeconfigError."""
        with patch("shutil.which", return_value="/usr/bin/gcloud"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=1,
                    stdout="",
                    stderr="Not authenticated",
                )
                with pytest.raises(KubeconfigError) as exc_info:
                    get_google_id_token()
        assert "Failed to get Google token" in str(exc_info.value)


class TestDecodeTokenClaims:
    """Tests for _decode_token_claims function."""

    def test_decode_token_claims_valid(self):
        """When token is valid it should extract claims."""
        import base64
        import json

        payload = {"email": "test@example.com", "hd": "example.com", "sub": "123"}
        encoded_payload = (
            base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        )
        token = f"header.{encoded_payload}.signature"

        result = _decode_token_claims(token)
        assert result["email"] == "test@example.com"
        assert result["hd"] == "example.com"
        assert result["sub"] == "123"

    def test_decode_token_claims_invalid(self):
        """When token is invalid it should return empty dict."""
        result = _decode_token_claims("invalid-token")
        assert result == {}


class TestUpsertByName:
    """Tests for _upsert_by_name function."""

    def test_upsert_by_name_append(self):
        """When item doesn't exist it should append."""
        items = [{"name": "a", "value": 1}]
        _upsert_by_name(items, {"name": "b", "value": 2})
        assert len(items) == 2
        assert items[1] == {"name": "b", "value": 2}

    def test_upsert_by_name_update(self):
        """When item exists it should update."""
        items = [{"name": "a", "value": 1}]
        _upsert_by_name(items, {"name": "a", "value": 99})
        assert len(items) == 1
        assert items[0] == {"name": "a", "value": 99}
