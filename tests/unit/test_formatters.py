"""Unit tests for output formatters."""

import json
from io import StringIO

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
                "message": (
                    "Controllers are provisioning resources "
                    "(19 minutes remaining) (1\ncontrollers working)"
                ),
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
        expected_msg = test_data["status"]["message"]  # type: ignore[index]
        actual_msg = parsed["status"]["message"]
        assert actual_msg == expected_msg

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
            "message": "Line1\nLine2\rLine3\tTabbed\x00Null\x1fControl",
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


class TestControllerStatusDisplay:
    """Tests for controller status display with HostedCluster conditions."""

    def test_displays_all_hostedcluster_conditions(self):
        """Test that all HostedCluster conditions are displayed, not just a subset."""
        # Create test data with multiple conditions (more than the old hardcoded 4)
        controller_data = {
            "controller_status": [
                {
                    "controller_name": "test-controller",
                    "observed_generation": 1,
                    "last_updated": "2025-12-09T10:00:00Z",
                    "conditions": [],
                    "metadata": {
                        "resources": {
                            "hostedcluster": {
                                "status": "Created",
                                "resource_status": {
                                    "conditions": [
                                        {"type": "Available", "status": "True"},
                                        {"type": "Progressing", "status": "False"},
                                        {"type": "Degraded", "status": "False"},
                                        {
                                            "type": "ClusterVersionSucceeding",
                                            "status": "True",
                                        },
                                        # These conditions were previously filtered out
                                        {
                                            "type": "GCPEndpointAvailable",
                                            "status": "True",
                                        },
                                        {
                                            "type": "GCPServiceAttachmentAvailable",
                                            "status": "True",
                                        },
                                        {
                                            "type": "ValidGCPWorkloadIdentity",
                                            "status": "True",
                                        },
                                        {"type": "EtcdAvailable", "status": "True"},
                                        {
                                            "type": "InfrastructureReady",
                                            "status": "True",
                                        },
                                        {
                                            "type": "ReconciliationSucceeded",
                                            "status": "True",
                                        },
                                    ]
                                },
                            }
                        }
                    },
                }
            ]
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="table")
        formatter.console.file = output_buffer

        formatter.print_controller_status(controller_data, "test-cluster-id")
        output = output_buffer.getvalue()

        # Verify ALL conditions are displayed, including those previously filtered
        assert "Available" in output
        assert "Progressing" in output
        assert "Degraded" in output
        assert "ClusterVersionSucceeding" in output
        # These were previously not shown - now they should be
        assert "GCPEndpointAvailable" in output
        assert "GCPServiceAttachmentAvailable" in output
        assert "ValidGCPWorkloadIdentity" in output
        assert "EtcdAvailable" in output
        assert "InfrastructureReady" in output
        assert "ReconciliationSucceeded" in output

    def test_condition_status_values_displayed(self):
        """Test that condition status values and messages are displayed."""
        # Use variables for messages to avoid line length issues
        msg_available = "The hosted control plane is available"
        msg_degraded = "The hosted cluster is not degraded"
        conditions = [
            {"type": "Available", "status": "True", "message": msg_available},
            {"type": "Degraded", "status": "False", "message": msg_degraded},
            {"type": "ExternalDNSReachable", "status": "Unknown"},
        ]
        controller_data = {
            "controller_status": [
                {
                    "controller_name": "test-controller",
                    "metadata": {
                        "resources": {
                            "hostedcluster": {
                                "status": "Created",
                                "resource_status": {"conditions": conditions},
                            }
                        }
                    },
                }
            ]
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="table")
        formatter.console.file = output_buffer

        formatter.print_controller_status(controller_data, "test-cluster-id")
        output = output_buffer.getvalue()

        # Verify status values are displayed
        assert "True" in output
        assert "False" in output
        assert "Unknown" in output

        # Verify messages are displayed (may be wrapped across lines by Rich)
        # Check key parts of messages are present
        assert "hosted control plane" in output
        assert "hosted cluster" in output
        # ExternalDNSReachable should still be shown without message
        assert "ExternalDNSReachable" in output

    def test_long_condition_names_not_truncated(self):
        """Test that long condition names are fully displayed."""
        # Use variables for long condition type names to avoid line length issues
        long_condition_1 = "ValidHostedControlPlaneConfiguration"
        long_condition_2 = "ClusterVersionRetrievedUpdates"
        conditions = [
            {"type": long_condition_1, "status": "True"},
            {"type": long_condition_2, "status": "False"},
        ]
        controller_data = {
            "controller_status": [
                {
                    "controller_name": "test-controller",
                    "metadata": {
                        "resources": {
                            "hostedcluster": {
                                "status": "Created",
                                "resource_status": {"conditions": conditions},
                            }
                        }
                    },
                }
            ]
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="table")
        formatter.console.file = output_buffer

        formatter.print_controller_status(controller_data, "test-cluster-id")
        output = output_buffer.getvalue()

        # Verify long names are not truncated (no ellipsis in condition names)
        assert "ValidHostedControlPlaneConfiguration" in output
        assert "ClusterVersionRetrievedUpdates" in output

    def test_empty_conditions_handled(self):
        """Test that empty conditions list is handled gracefully."""
        controller_data = {
            "controller_status": [
                {
                    "controller_name": "test-controller",
                    "metadata": {
                        "resources": {
                            "hostedcluster": {
                                "status": "Created",
                                "resource_status": {"conditions": []},
                            }
                        }
                    },
                }
            ]
        }

        output_buffer = StringIO()
        formatter = OutputFormatter(format_type="table")
        formatter.console.file = output_buffer

        # Should not raise an exception
        formatter.print_controller_status(controller_data, "test-cluster-id")
        output = output_buffer.getvalue()

        # Should still show the resource
        assert "Hostedcluster" in output
