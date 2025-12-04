"""Output formatting utilities for GCP HCP CLI."""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)


class OutputFormatter:
    """Output formatter supporting multiple formats like gcloud CLI."""

    def __init__(
        self, format_type: str = "table", console: Optional[Console] = None
    ) -> None:
        """Initialize output formatter.

        Args:
            format_type: Output format (table, json, yaml, csv, value)
            console: Rich console for output
        """
        self.format_type = format_type.lower()
        self.console = console or Console()

    def print_data(self, data: Any) -> None:
        """Print data in the configured format.

        Args:
            data: Data to print
        """
        if self.format_type == "json":
            self._print_json(data)
        elif self.format_type == "yaml":
            self._print_yaml(data)
        elif self.format_type == "csv":
            self._print_csv(data)
        elif self.format_type == "value":
            self._print_value(data)
        else:  # table or fallback
            self._print_table_data(data)

    def print_table(
        self,
        data: List[Dict[str, Any]],
        title: Optional[str] = None,
        columns: Optional[List[str]] = None,
    ) -> None:
        """Print data as a table.

        Args:
            data: List of dictionaries to display
            title: Optional table title
            columns: Optional list of column names to include
        """
        if not data:
            if title:
                self.console.print(f"[yellow]No data found for {title}[/yellow]")
            return

        if self.format_type != "table":
            self.print_data(data)
            return

        # Create table
        table = Table(title=title, show_header=True, header_style="bold blue")

        # Determine columns
        if columns:
            table_columns = columns
        else:
            # Use keys from first item
            table_columns = list(data[0].keys())

        # Add columns
        for column in table_columns:
            table.add_column(column, style="white")

        # Add rows
        for item in data:
            row = [str(item.get(col, "")) for col in table_columns]
            table.add_row(*row)

        self.console.print(table)

    def print_resource_details(
        self,
        resource: Dict[str, Any],
        title: Optional[str] = None,
    ) -> None:
        """Print detailed resource information.

        Args:
            resource: Resource data to display
            title: Optional title for the details
        """
        if self.format_type != "table":
            self.print_data(resource)
            return

        # Create details table
        table = Table(title=title, show_header=False, box=None)
        table.add_column("Field", style="cyan", width=20)
        table.add_column("Value", style="white")

        # Add basic fields
        basic_fields = [
            "id",
            "name",
            "target_project_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        for field in basic_fields:
            if field in resource:
                value = resource[field]
                if field.endswith("_at") and value:
                    value = self.format_datetime(value)
                table.add_row(field.replace("_", " ").title(), str(value))

        # Add status information
        if "status" in resource:
            status = resource["status"]
            table.add_row("", "")  # Separator
            table.add_row("Status", "")

            if isinstance(status, dict):
                for key, value in status.items():
                    if key == "conditions" and isinstance(value, list):
                        for i, condition in enumerate(value):
                            condition_text = (
                                f"  {condition.get('type', 'Unknown')}: "
                                f"{condition.get('status', 'Unknown')}"
                            )
                            if condition.get("message"):
                                condition_text += f" ({condition['message']})"
                            table.add_row(f"  Condition {i+1}", condition_text)
                    else:
                        table.add_row(f"  {key.replace('_', ' ').title()}", str(value))

        # Add spec information if present
        if "spec" in resource and resource["spec"]:
            table.add_row("", "")  # Separator
            table.add_row("Specification", "")
            spec = resource["spec"]
            if isinstance(spec, dict):
                for key, value in spec.items():
                    if isinstance(value, (dict, list)):
                        value = f"[{type(value).__name__}]"
                    table.add_row(f"  {key.replace('_', ' ').title()}", str(value))

        self.console.print(table)

    def print_cluster_status(
        self, cluster_data: Dict[str, Any], cluster_id: str
    ) -> None:
        """Print formatted cluster status information.

        Args:
            cluster_data: Full cluster data including status
            cluster_id: Cluster identifier
        """
        if self.format_type != "table":
            # For non-table formats, just show the status section
            status_section = {
                "cluster_id": cluster_id,
                "cluster_name": cluster_data.get("name", "Unknown"),
                "status": cluster_data.get("status", {}),
            }
            self.print_data(status_section)
            return

        # Create status-focused table
        table = Table(
            title=f"Status: {cluster_data.get('name', cluster_id)}",
            show_header=False,
            box=None,
        )
        table.add_column("Field", style="cyan", width=20)
        table.add_column("Value", style="white")

        # Basic cluster info
        table.add_row("Cluster ID", cluster_id)
        table.add_row("Cluster Name", cluster_data.get("name", "Unknown"))
        table.add_row("Project", cluster_data.get("target_project_id", "Unknown"))
        table.add_row("Created By", cluster_data.get("created_by", "Unknown"))

        # Network configuration (from spec.platform.gcp)
        spec = cluster_data.get("spec", {})
        platform = spec.get("platform", {})
        gcp_config = platform.get("gcp", {})
        if gcp_config:
            table.add_row("", "")  # Separator
            table.add_row("[bold]Network Configuration[/bold]", "")
            if gcp_config.get("network"):
                table.add_row("  Network", gcp_config["network"])
            if gcp_config.get("subnet"):
                table.add_row("  Subnet", gcp_config["subnet"])
            endpoint_access = gcp_config.get("endpointAccess", "Private")
            table.add_row("  Endpoint Access", endpoint_access)

        status = cluster_data.get("status", {})
        if status:
            table.add_row("", "")  # Separator
            table.add_row("[bold]Current Status[/bold]", "")

            # Phase with color coding
            phase = status.get("phase", "Unknown")
            phase_color = {
                "Ready": "green",
                "Progressing": "yellow",
                "Pending": "blue",
                "Failed": "red",
            }.get(phase, "white")
            table.add_row("  Phase", f"[{phase_color}]{phase}[/{phase_color}]")

            # Generation info
            if "observedGeneration" in status:
                gen_current = status["observedGeneration"]
                gen_desired = cluster_data.get("generation", gen_current)
                if gen_current == gen_desired:
                    gen_status = f"[green]{gen_current}[/green] (up to date)"
                else:
                    gen_status = (
                        f"[yellow]{gen_current}[/yellow] (desired: {gen_desired})"
                    )
                table.add_row("  Generation", gen_status)

            # Status message
            if status.get("message"):
                table.add_row("  Message", status["message"])

            if status.get("reason"):
                table.add_row("  Reason", status["reason"])

            # Last update time
            if status.get("lastUpdateTime"):
                update_time = self.format_datetime(status["lastUpdateTime"])
                table.add_row("  Last Update", update_time)

            # Conditions
            conditions = status.get("conditions", [])
            if conditions:
                table.add_row("", "")  # Separator
                table.add_row("[bold]Conditions[/bold]", "")

                for i, condition in enumerate(conditions):
                    condition_type = condition.get("type", "Unknown")
                    condition_status = condition.get("status", "Unknown")
                    condition_message = condition.get("message", "")

                    # Color code the status
                    status_color = {
                        "True": "green",
                        "False": "red",
                        "Unknown": "yellow",
                    }.get(condition_status, "white")

                    status_text = f"[{status_color}]{condition_status}[/{status_color}]"
                    if condition_message:
                        status_text += f" - {condition_message}"

                    table.add_row(f"  {condition_type}", status_text)

                    # Add transition time if available
                    if condition.get("lastTransitionTime"):
                        transition_time = self.format_datetime(
                            condition["lastTransitionTime"]
                        )
                        table.add_row(
                            "    Last Transition", f"[dim]{transition_time}[/dim]"
                        )

        # Platform information
        spec = cluster_data.get("spec", {})
        platform = spec.get("platform", {})
        if platform:
            table.add_row("", "")  # Separator
            table.add_row("[bold]Platform[/bold]", "")
            table.add_row("  Type", platform.get("type", "Unknown"))

            if platform.get("gcp"):
                gcp_info = platform["gcp"]
                table.add_row("  GCP Project", gcp_info.get("projectID", "Unknown"))
                table.add_row("  GCP Region", gcp_info.get("region", "Unknown"))

        self.console.print(table)

    def print_controller_status(
        self, controller_data: Dict[str, Any], cluster_id: str
    ) -> None:
        """Print detailed controller status information.

        Args:
            controller_data: Controller status data from /clusters/<id>/status endpoint
            cluster_id: Cluster identifier
        """
        if self.format_type != "table":
            # For non-table formats, the data is already included in the main output
            return

        controller_statuses = controller_data.get("controller_status", [])
        if not controller_statuses:
            return

        # Create controller status table
        table = Table(
            title="[bold cyan]Controller Status Details[/bold cyan]",
            show_header=False,
            box=None,
        )
        table.add_column("Field", style="cyan", width=25)
        table.add_column("Value", style="white")

        for i, controller in enumerate(controller_statuses):
            if i > 0:
                table.add_row("", "")  # Separator between controllers

            controller_name = controller.get("controller_name", "Unknown")
            table.add_row(
                f"[bold]Controller {i+1}[/bold]", f"[bold]{controller_name}[/bold]"
            )

            # Controller-level info
            if controller.get("observed_generation"):
                table.add_row(
                    "  Observed Generation", str(controller["observed_generation"])
                )

            if controller.get("last_updated"):
                last_updated = self.format_datetime(controller["last_updated"])
                table.add_row("  Last Updated", last_updated)

            # Controller conditions
            conditions = controller.get("conditions", [])
            if conditions:
                table.add_row("  Conditions", "")
                for condition in conditions:
                    condition_type = condition.get("type", "Unknown")
                    condition_status = condition.get("status", "Unknown")
                    condition_message = condition.get("message", "")

                    # Color code the status
                    status_color = {
                        "True": "green",
                        "False": "red",
                        "Unknown": "yellow",
                    }.get(condition_status, "white")

                    status_text = f"[{status_color}]{condition_status}[/{status_color}]"
                    if condition_message:
                        # Truncate very long messages
                        if len(condition_message) > 80:
                            condition_message = condition_message[:77] + "..."
                        status_text += f" - {condition_message}"

                    table.add_row(f"    {condition_type}", status_text)

            # Resource details from metadata
            metadata = controller.get("metadata", {})
            resources = metadata.get("resources", {})
            if resources:
                table.add_row("  Resources", "")
                for resource_type, resource_data in resources.items():
                    resource_status = resource_data.get("status", "Unknown")
                    status_color = {
                        "Created": "green",
                        "Ready": "green",
                        "Available": "green",
                        "Failed": "red",
                        "Pending": "yellow",
                    }.get(resource_status, "white")

                    table.add_row(
                        f"    {resource_type.title()}",
                        f"[{status_color}]{resource_status}[/{status_color}]",
                    )

                    # Show hosted cluster conditions if available
                    if resource_type == "hostedcluster":
                        hc_status = resource_data.get("resource_status", {})
                        hc_conditions = hc_status.get("conditions", [])

                        # Show a few key conditions
                        key_conditions = [
                            "Available",
                            "Progressing",
                            "Degraded",
                            "ClusterVersionSucceeding",
                        ]
                        for condition in hc_conditions:
                            condition_type = condition.get("type", "")
                            if condition_type in key_conditions:
                                condition_status = condition.get("status", "Unknown")
                                condition_reason = condition.get("reason", "")

                                status_color = {
                                    "True": (
                                        "green"
                                        if condition_type != "Degraded"
                                        else "red"
                                    ),
                                    "False": (
                                        "red"
                                        if condition_type
                                        in ["Available", "ClusterVersionSucceeding"]
                                        else "green"
                                    ),
                                    "Unknown": "yellow",
                                }.get(condition_status, "white")

                                display_text = (
                                    f"[{status_color}]{condition_status}"
                                    f"[/{status_color}]"
                                )
                                if condition_reason:
                                    display_text += f" ({condition_reason})"

                                table.add_row(f"      {condition_type}", display_text)

        self.console.print("\n")  # Add some spacing
        self.console.print(table)

    def print_original_cluster_status(
        self, status_data: Dict[str, Any], cluster_id: str
    ) -> None:
        """Print cluster status information.

        Args:
            status_data: Status data from API
            cluster_id: Cluster identifier
        """
        if self.format_type != "table":
            self.print_data(status_data)
            return

        # Overall status panel
        phase = status_data.get("phase", "Unknown")
        phase_color = {
            "Ready": "green",
            "Progressing": "yellow",
            "Pending": "blue",
            "Failed": "red",
        }.get(phase, "white")

        status_text = Text()
        status_text.append(f"Phase: {phase}\n", style=f"{phase_color} bold")

        if "message" in status_data:
            status_text.append(f"Message: {status_data['message']}\n", style="dim")

        if "generation" in status_data:
            status_text.append(
                f"Generation: {status_data['generation']}\n", style="dim"
            )

        panel = Panel(
            status_text,
            title=f"[bold]Cluster Status: {cluster_id}[/bold]",
            border_style=phase_color,
        )
        self.console.print(panel)

        # Conditions table
        conditions = status_data.get("conditions", [])
        if conditions:
            table = Table(
                title="Conditions", show_header=True, header_style="bold blue"
            )
            table.add_column("Type", style="cyan")
            table.add_column("Status", style="white")
            table.add_column("Last Transition", style="dim")
            table.add_column("Message", style="white")

            for condition in conditions:
                last_transition = condition.get("lastTransitionTime", "")
                if last_transition:
                    last_transition = self.format_datetime(last_transition)

                status_style = "green" if condition.get("status") == "True" else "red"

                table.add_row(
                    condition.get("type", ""),
                    f"[{status_style}]{condition.get('status', '')}[/{status_style}]",
                    last_transition,
                    condition.get("message", ""),
                )

            self.console.print(table)

        # Controller statuses
        controller_statuses = status_data.get("controllerStatuses", [])
        if controller_statuses:
            table = Table(
                title="Controller Statuses", show_header=True, header_style="bold blue"
            )
            table.add_column("Controller", style="cyan")
            table.add_column("Status", style="white")
            table.add_column("Last Updated", style="dim")

            for controller in controller_statuses:
                last_updated = controller.get("lastUpdated", "")
                if last_updated:
                    last_updated = self.format_datetime(last_updated)

                table.add_row(
                    controller.get("name", ""),
                    controller.get("status", ""),
                    last_updated,
                )

            self.console.print(table)

    def format_datetime(self, dt_string: Optional[str]) -> str:
        """Format datetime string for display.

        Args:
            dt_string: ISO datetime string

        Returns:
            Formatted datetime string
        """
        if not dt_string:
            return ""

        try:
            # Parse ISO format datetime
            dt = datetime.fromisoformat(dt_string.replace("Z", "+00:00"))
            return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        except Exception:
            # Return original string if parsing fails
            return dt_string

    def _print_json(self, data: Any) -> None:
        """Print data as JSON."""
        try:
            json_str = json.dumps(data, indent=2, default=str)
            self.console.print(json_str)
        except Exception as e:
            logger.error(f"Failed to format as JSON: {e}")
            self.console.print(str(data))

    def _print_yaml(self, data: Any) -> None:
        """Print data as YAML."""
        try:
            yaml_str = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            self.console.print(yaml_str)
        except Exception as e:
            logger.error(f"Failed to format as YAML: {e}")
            self.console.print(str(data))

    def _print_csv(self, data: Any) -> None:
        """Print data as CSV."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            # Print header
            headers = list(data[0].keys())
            self.console.print(",".join(headers))

            # Print rows
            for item in data:
                row = [str(item.get(header, "")) for header in headers]
                # Escape commas and quotes
                escaped_row = []
                for field in row:
                    if "," in field or '"' in field:
                        # Escape double quotes by doubling them, then wrap in quotes
                        escaped_field = field.replace('"', '""')
                        field = f'"{escaped_field}"'
                    escaped_row.append(field)
                self.console.print(",".join(escaped_row))
        else:
            # Single value or non-dict data
            self.console.print(str(data))

    def _print_value(self, data: Any) -> None:
        """Print data as raw values."""
        if isinstance(data, list):
            for item in data:
                self.console.print(str(item))
        elif isinstance(data, dict):
            for value in data.values():
                self.console.print(str(value))
        else:
            self.console.print(str(data))

    def _print_table_data(self, data: Any) -> None:
        """Print data in table format (fallback for complex data)."""
        if isinstance(data, list) and data and isinstance(data[0], dict):
            self.print_table(data)
        elif isinstance(data, dict):
            # Convert dict to key-value table
            table = Table(show_header=False, box=None)
            table.add_column("Key", style="cyan")
            table.add_column("Value", style="white")

            for key, value in data.items():
                if isinstance(value, (dict, list)):
                    value = f"[{type(value).__name__}]"
                table.add_row(str(key), str(value))

            self.console.print(table)
        else:
            self.console.print(str(data))
