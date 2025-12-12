"""Unit tests for nodepool commands."""

import pytest
from unittest.mock import MagicMock
from click import ClickException

from gcphcp.cli.commands.nodepools import resolve_nodepool_identifier


class TestResolveNodepoolIdentifier:
    """Test cases for resolve_nodepool_identifier function."""

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client."""
        return MagicMock()

    def test_unique_nodepool_name_resolves_successfully(self, mock_api_client):
        """Test that a unique nodepool name resolves without error."""
        # Mock API response with a single nodepool
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1234-1234-1234-123456789abc",
                    "name": "my-nodepool",
                    "cluster_id": "cluster-1",
                }
            ]
        }

        result = resolve_nodepool_identifier(mock_api_client, "my-nodepool")

        assert result == "abc12345-1234-1234-1234-123456789abc"
        mock_api_client.get.assert_called_once_with(
            "/api/v1/nodepools", params={"limit": 100}
        )

    def test_ambiguous_nodepool_name_raises_error(self, mock_api_client):
        """Test that multiple nodepools with same name raise an error."""
        # Mock API response with multiple nodepools with same name
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1111-1111-1111-111111111111",
                    "name": "my-nodepool",
                    "cluster_id": "cluster-1",
                },
                {
                    "id": "def67890-2222-2222-2222-222222222222",
                    "name": "my-nodepool",
                    "cluster_id": "cluster-2",
                },
                {
                    "id": "ghi13579-3333-3333-3333-333333333333",
                    "name": "my-nodepool",
                    "clusterId": "cluster-3",  # Test both snake_case and camelCase
                },
            ]
        }

        with pytest.raises(ClickException) as exc_info:
            resolve_nodepool_identifier(mock_api_client, "my-nodepool")

        error_message = str(exc_info.value)
        assert "Multiple nodepools named 'my-nodepool' found" in error_message
        assert "abc12345-1111-1111-1111-111111111111" in error_message
        assert "def67890-2222-2222-2222-222222222222" in error_message
        assert "ghi13579-3333-3333-3333-333333333333" in error_message
        assert "cluster-1" in error_message
        assert "cluster-2" in error_message
        assert "cluster-3" in error_message
        assert "--cluster" in error_message
        assert "partial nodepool id" in error_message.lower()

    def test_ambiguous_name_with_cluster_flag_resolves(self, mock_api_client):
        """Test that ambiguous name with --cluster flag resolves correctly."""
        # Mock API response filtered by cluster
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1111-1111-1111-111111111111",
                    "name": "my-nodepool",
                    "cluster_id": "cluster-1",
                }
            ]
        }

        result = resolve_nodepool_identifier(
            mock_api_client, "my-nodepool", cluster_id="cluster-1"
        )

        assert result == "abc12345-1111-1111-1111-111111111111"
        mock_api_client.get.assert_called_once_with(
            "/api/v1/nodepools", params={"limit": 100, "clusterId": "cluster-1"}
        )

    def test_full_uuid_resolves_directly(self, mock_api_client):
        """Test that a full UUID is tried directly first."""
        full_uuid = "abc12345-1234-1234-1234-123456789abc"
        mock_api_client.get.return_value = {"id": full_uuid, "name": "my-nodepool"}

        result = resolve_nodepool_identifier(mock_api_client, full_uuid)

        assert result == full_uuid
        mock_api_client.get.assert_called_once_with(f"/api/v1/nodepools/{full_uuid}")

    def test_partial_id_resolves_uniquely(self, mock_api_client):
        """Test that a partial ID (8+ chars) resolves when unique."""
        # Mock list nodepools response
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1234-1234-1234-123456789abc",
                    "name": "nodepool-1",
                    "cluster_id": "cluster-1",
                },
                {
                    "id": "def67890-5678-5678-5678-567890abcdef",
                    "name": "nodepool-2",
                    "cluster_id": "cluster-2",
                },
            ]
        }

        result = resolve_nodepool_identifier(mock_api_client, "abc12345")

        assert result == "abc12345-1234-1234-1234-123456789abc"

    def test_partial_id_ambiguous_raises_error(self, mock_api_client):
        """Test that ambiguous partial ID raises an error."""
        # Mock API response with multiple nodepools matching partial ID
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1111-1111-1111-111111111111",
                    "name": "nodepool-1",
                    "cluster_id": "cluster-1",
                },
                {
                    "id": "abc12345-2222-2222-2222-222222222222",
                    "name": "nodepool-2",
                    "cluster_id": "cluster-2",
                },
            ]
        }

        with pytest.raises(ClickException) as exc_info:
            resolve_nodepool_identifier(mock_api_client, "abc12345")

        error_message = str(exc_info.value)
        assert "Multiple nodepools match 'abc12345'" in error_message
        assert "nodepool-1" in error_message
        assert "nodepool-2" in error_message

    def test_no_match_raises_error(self, mock_api_client):
        """Test that no match raises an appropriate error."""
        mock_api_client.get.return_value = {"nodepools": []}

        with pytest.raises(ClickException) as exc_info:
            resolve_nodepool_identifier(mock_api_client, "nonexistent")

        error_message = str(exc_info.value)
        assert "No nodepool found with identifier 'nonexistent'" in error_message
        assert "gcphcp nodepools list" in error_message

    def test_partial_id_too_short_falls_through(self, mock_api_client):
        """Test that partial ID shorter than 8 chars is not tried."""
        mock_api_client.get.return_value = {
            "nodepools": [
                {
                    "id": "abc12345-1234-1234-1234-123456789abc",
                    "name": "nodepool-1",
                    "cluster_id": "cluster-1",
                }
            ]
        }

        # Short partial ID (< 8 chars) should not match by partial ID
        with pytest.raises(ClickException) as exc_info:
            resolve_nodepool_identifier(mock_api_client, "abc123")

        error_message = str(exc_info.value)
        assert "No nodepool found" in error_message
