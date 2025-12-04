"""Unit tests for output formatters."""

import json
from io import StringIO
import pytest

from gcphcp.utils.formatters import OutputFormatter


class TestOutputFormatter:
    """Tests for OutputFormatter class."""

    def test_json_output_escapes_newlines(self):
        """Test that JSON output properly escapes newline characters.

        This is a regression test for GCP-269 where JSON output contained
        literal newline characters instead of escaped \\n sequences.
        """
        # Create test data that mimics cluster status with newlines
        test_data = {
            "cluster_id": "test-cluster",
            "cluster_name": "test-cluster-name",
            "status": {
                "phase": "Progressing",
                "message": "Controllers are provisioning resources (19 minutes remaining) (1\ncontrollers working)",
                "conditions": [
                    {
                        "type": "Available",
                        "status": "False",
                        "message": "Multi-line message\nwith newlines",
                        "lastTransitionTime": "2025-12-04T10:00:00Z",
                    }
                ],
            },
        }

        # Capture output
        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="json")
        formatter.console.file = output_buffer

        # Print the data
        formatter.print_data(test_data)

        # Get the output
        json_output = output_buffer.getvalue()

        # Verify the output is valid JSON
        parsed = json.loads(json_output)
        assert parsed["status"]["message"] == test_data["status"]["message"]

        # Verify newlines are properly escaped in raw JSON string
        # The raw JSON should contain \\n (escaped) not literal newlines
        assert "\\n" in json_output, "JSON should contain escaped newlines (\\n)"

        # Ensure there are no literal newlines within JSON string values
        # Split by newlines and check that each line (except last) ends with valid JSON
        lines = json_output.rstrip("\n").split("\n")
        # The JSON is indented, so we expect multiple lines for formatting
        # But within string values, there should be no literal newlines

        # Key test: the message field should have \\n not a literal newline
        # Find the line with the message
        message_lines = [line for line in lines if "controllers working" in line]
        assert len(message_lines) == 1, (
            "Message with newline should appear on a single line in JSON, "
            "not split across multiple lines"
        )

    def test_json_output_escapes_control_characters(self):
        """Test that JSON output escapes various control characters."""
        test_data = {
            "message": "Line1\nLine2\rLine3\tTabbed\x00Null\x1FControl",
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="json")
        formatter.console.file = output_buffer

        formatter.print_data(test_data)
        json_output = output_buffer.getvalue()

        # Should be valid JSON
        parsed = json.loads(json_output)
        assert parsed["message"] == test_data["message"]

        # Should contain escape sequences
        assert "\\n" in json_output
        assert "\\r" in json_output
        assert "\\t" in json_output

    def test_json_output_handles_unicode(self):
        """Test that JSON output handles Unicode characters correctly."""
        test_data = {
            "message": "Hello 世界 🌍",
            "emoji": "✅ ❌ ⚠️",
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="json")
        formatter.console.file = output_buffer

        formatter.print_data(test_data)
        json_output = output_buffer.getvalue()

        # Should be valid JSON
        parsed = json.loads(json_output)
        assert parsed["message"] == test_data["message"]
        assert parsed["emoji"] == test_data["emoji"]

    def test_json_output_handles_nested_structures(self):
        """Test that JSON output handles deeply nested structures."""
        test_data = {
            "level1": {
                "level2": {
                    "level3": {
                        "message": "Deep\nnesting\nwith\nnewlines",
                    }
                }
            }
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="json")
        formatter.console.file = output_buffer

        formatter.print_data(test_data)
        json_output = output_buffer.getvalue()

        # Should be valid JSON
        parsed = json.loads(json_output)
        assert (
            parsed["level1"]["level2"]["level3"]["message"]
            == test_data["level1"]["level2"]["level3"]["message"]
        )

    def test_json_output_with_list_of_objects(self):
        """Test JSON output with lists containing objects with newlines."""
        test_data = [
            {"id": 1, "message": "First\nmessage"},
            {"id": 2, "message": "Second\nmessage"},
        ]

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="json")
        formatter.console.file = output_buffer

        formatter.print_data(test_data)
        json_output = output_buffer.getvalue()

        # Should be valid JSON
        parsed = json.loads(json_output)
        assert len(parsed) == 2
        assert parsed[0]["message"] == "First\nmessage"
        assert parsed[1]["message"] == "Second\nmessage"
