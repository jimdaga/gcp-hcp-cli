"""NodePool management commands for GCP HCP CLI."""

import time
from typing import Dict, Optional, TYPE_CHECKING

import click
from rich.panel import Panel
from rich.table import Table

from ...client.exceptions import APIError, ResourceNotFoundError, ValidationError
from ...models.nodepool import NodePool

if TYPE_CHECKING:
    from ..main import CLIContext


def resolve_nodepool_identifier(
    api_client, identifier: str, cluster_id: Optional[str] = None
) -> str:
    """Resolve nodepool identifier (name, partial ID, or full ID) to full nodepool ID.

    Args:
        api_client: API client instance
        identifier: NodePool name, partial ID (>=8 chars), or full ID
        cluster_id: Optional cluster ID to narrow search

    Returns:
        Full nodepool ID (UUID)

    Raises:
        click.ClickException: If no nodepool found or multiple matches
    """
    # If it looks like a full UUID, try it directly first
    if len(identifier) == 36 and identifier.count("-") == 4:
        try:
            # Test if it exists by fetching it
            api_client.get(f"/api/v1/nodepools/{identifier}")
            return identifier
        except ResourceNotFoundError:
            pass

    # Build search params
    params = {"limit": 100}
    if cluster_id:
        params["clusterId"] = cluster_id

    # Search through nodepools
    try:
        response = api_client.get("/api/v1/nodepools", params=params)
        nodepools = response.get("nodepools") or []

        # Try exact name match first
        for nodepool in nodepools:
            if nodepool.get("name") == identifier:
                return nodepool.get("id")

        # Try partial ID match (case-insensitive, minimum 8 chars)
        if len(identifier) >= 8:
            identifier_lower = identifier.lower()
            matches = []
            for nodepool in nodepools:
                nodepool_id = nodepool.get("id", "")
                if nodepool_id.lower().startswith(identifier_lower):
                    matches.append((nodepool.get("id"), nodepool.get("name")))

            if len(matches) == 1:
                return matches[0][0]  # Return the ID
            elif len(matches) > 1:
                match_list = "\n".join([f"  {id} ({name})" for id, name in matches])
                raise click.ClickException(
                    f"Multiple nodepools match '{identifier}':\n{match_list}\n"
                    "Please provide a more specific identifier."
                )

        # No matches found
        raise click.ClickException(
            f"No nodepool found with identifier '{identifier}'. "
            "Use 'gcphcp nodepools list --cluster <cluster-id>' to see available nodepools."
        )

    except APIError as e:
        raise click.ClickException(f"Failed to search nodepools: {e}")


def parse_labels(labels_tuple: tuple) -> Dict[str, str]:
    """Parse labels from CLI format (key=value) to dictionary.

    Args:
        labels_tuple: Tuple of label strings in key=value format

    Returns:
        Dictionary of labels

    Raises:
        click.ClickException: If label format is invalid
    """
    labels = {}
    for label in labels_tuple:
        if "=" not in label:
            raise click.ClickException(
                f"Invalid label format '{label}'. Expected 'key=value'."
            )
        key, value = label.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels


def parse_taints(taints_tuple: tuple) -> list:
    """Parse taints from CLI format (key=value:effect) to list of dicts.

    Args:
        taints_tuple: Tuple of taint strings in key=value:effect format

    Returns:
        List of taint dictionaries

    Raises:
        click.ClickException: If taint format is invalid
    """
    taints = []
    for taint in taints_tuple:
        if "=" not in taint or ":" not in taint:
            raise click.ClickException(
                f"Invalid taint format '{taint}'. Expected 'key=value:effect'."
            )
        key_value, effect = taint.rsplit(":", 1)
        if "=" not in key_value:
            raise click.ClickException(
                f"Invalid taint format '{taint}'. Expected 'key=value:effect'."
            )
        key, value = key_value.split("=", 1)
        taints.append({
            "key": key.strip(),
            "value": value.strip(),
            "effect": effect.strip()
        })
    return taints


@click.group("nodepools")
def nodepools_group() -> None:
    """Manage nodepools for clusters."""
    pass


@nodepools_group.command("list")
@click.option(
    "--cluster",
    required=True,
    help="Cluster identifier (name, partial ID, or full UUID)"
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="Maximum number of nodepools to list (default: 50)"
)
@click.pass_obj
def list_nodepools(
    cli_context: "CLIContext",
    cluster: str,
    limit: int
) -> None:
    """List nodepools for a cluster.

    Shows a table of nodepools with their basic information including
    name, status, node counts, and creation date.

    \b
    Examples:
        gcphcp nodepools list --cluster demo08
        gcphcp nodepools list --cluster 3c7f2227
        gcphcp nodepools list --cluster my-cluster --limit 100
    """
    from .clusters import resolve_cluster_identifier

    try:
        api_client = cli_context.get_api_client()

        # Resolve cluster identifier to UUID
        cluster_id = resolve_cluster_identifier(api_client, cluster)

        # Fetch nodepools
        response = api_client.get(
            "/api/v1/nodepools",
            params={"clusterId": cluster_id, "limit": limit}
        )
        nodepools_data = response.get("nodepools") or []

        # Handle empty list
        if not nodepools_data:
            if not cli_context.quiet:
                cli_context.console.print(
                    f"[yellow]No nodepools found for cluster {cluster}[/yellow]"
                )
                cli_context.console.print(
                    f"[dim]Create one with:[/dim] gcphcp nodepools create <name> "
                    f"--cluster {cluster} --replicas <N>"
                )
            return

        # Handle non-table formats
        if cli_context.output_format != "table":
            cli_context.formatter.print_data({"nodepools": nodepools_data})
            return

        # Create table
        table = Table(title=f"NodePools for cluster {cluster}", show_header=True)
        table.add_column("NAME", style="cyan")
        table.add_column("ID", style="dim")
        table.add_column("STATUS", style="white")
        table.add_column("NODES", style="white")
        table.add_column("AGE", style="dim")

        for np_data in nodepools_data:
            nodepool = NodePool.from_api_response(np_data)

            # Status with color
            status = nodepool.get_display_status()
            status_color = {
                "Ready": "green",
                "Progressing": "yellow",
                "Pending": "blue",
                "Failed": "red",
            }.get(status, "white")

            # ID (show first 8 chars)
            short_id = nodepool.id[:8] if len(nodepool.id) > 8 else nodepool.id

            table.add_row(
                nodepool.name,
                short_id,
                f"[{status_color}]{status}[/{status_color}]",
                nodepool.get_node_info(),
                nodepool.get_age(),
            )

        cli_context.console.print(table)

    except click.ClickException:
        raise
    except APIError as e:
        cli_context.console.print(f"[red]API error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@nodepools_group.command("create")
@click.argument("nodepool_name")
@click.option(
    "--cluster",
    required=True,
    help="Cluster identifier (name, partial ID, or full UUID)"
)
@click.option(
    "--replicas",
    type=int,
    required=True,
    help="Number of compute nodes to create"
)
@click.option(
    "--instance-type",
    "--machine-type",
    default="n1-standard-4",
    help="GCP machine type (default: n1-standard-4)"
)
@click.option(
    "--disk-size",
    type=int,
    default=128,
    help="Boot disk size in GB (default: 128)"
)
@click.option(
    "--disk-type",
    type=click.Choice(["pd-standard", "pd-ssd", "pd-balanced"], case_sensitive=False),
    default="pd-standard",
    help="Boot disk type (default: pd-standard)"
)
@click.option(
    "--auto-repair/--no-auto-repair",
    default=True,
    help="Enable auto-repair (default: enabled)"
)
@click.option(
    "--labels",
    multiple=True,
    help="Node labels in key=value format (can be specified multiple times)"
)
@click.option(
    "--taints",
    multiple=True,
    help="Node taints in key=value:effect format (can be specified multiple times)"
)
@click.pass_obj
def create_nodepool(
    cli_context: "CLIContext",
    nodepool_name: str,
    cluster: str,
    replicas: int,
    instance_type: str,
    disk_size: int,
    disk_type: str,
    auto_repair: bool,
    labels: tuple,
    taints: tuple,
) -> None:
    """Create a new nodepool for a cluster.

    NODEPOOL_NAME: Name for the new nodepool (must be unique within cluster).

    \b
    Examples:
        gcphcp nodepools create workers --cluster demo08 --replicas 3
        gcphcp nodepools create gpu-nodes --cluster demo08 --replicas 2 \\
            --instance-type n1-standard-8 --disk-size 256
        gcphcp nodepools create workers --cluster demo08 --replicas 3 \\
            --labels env=prod --labels team=platform
    """
    from .clusters import resolve_cluster_identifier

    try:
        api_client = cli_context.get_api_client()

        # Validate inputs
        if replicas <= 0:
            raise click.ClickException("Replicas must be greater than 0")

        # Resolve cluster identifier to UUID
        cluster_id = resolve_cluster_identifier(api_client, cluster)

        # Parse labels and taints
        parsed_labels = parse_labels(labels) if labels else {}
        parsed_taints = parse_taints(taints) if taints else []

        # Build nodepool spec
        nodepool_data = {
            "name": nodepool_name,
            "cluster_id": cluster_id,
            "spec": {
                "replicas": replicas,
                "platform": {
                    "type": "GCP",
                    "gcp": {
                        "instanceType": instance_type,
                        "rootVolume": {
                            "size": disk_size,
                            "type": disk_type
                        }
                    }
                },
                "management": {
                    "autoRepair": auto_repair,
                    "upgradeType": "Replace"
                }
            }
        }

        # Add labels and taints if provided
        if parsed_labels:
            nodepool_data["spec"]["platform"]["gcp"]["labels"] = parsed_labels
        if parsed_taints:
            nodepool_data["spec"]["platform"]["gcp"]["taints"] = parsed_taints

        if not cli_context.quiet:
            cli_context.console.print(f"[bold cyan]Creating NodePool '{nodepool_name}'...[/bold cyan]")

        # Create nodepool
        response = api_client.post("/api/v1/nodepools", json_data=nodepool_data)

        # Display success
        if not cli_context.quiet:
            nodepool_id = response.get("id", "unknown")
            panel = Panel(
                f"[green]✓[/green] NodePool '{nodepool_name}' created successfully\n\n"
                f"ID: {nodepool_id}\n"
                f"Replicas: {replicas}\n"
                f"Machine Type: {instance_type}\n"
                f"Disk: {disk_size}GB {disk_type}\n\n"
                f"[dim]Use 'gcphcp nodepools status {nodepool_id[:8]}' to monitor creation[/dim]",
                title="[bold green]NodePool Created[/bold green]",
                border_style="green"
            )
            cli_context.console.print(panel)
        else:
            # In quiet mode, print ID for scripting
            cli_context.console.print(response.get("id"))

    except click.ClickException:
        raise
    except ValidationError as e:
        cli_context.console.print(f"[red]Validation error: {e}[/red]")
        raise click.ClickException(str(e))
    except APIError as e:
        cli_context.console.print(f"[red]API error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@nodepools_group.command("status")
@click.argument("nodepool_identifier")
@click.option(
    "--cluster",
    help="Cluster identifier to narrow nodepool search (enables name-based lookup)"
)
@click.option(
    "--detailed",
    "-d",
    is_flag=True,
    help="Show detailed status including all conditions and management configuration"
)
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    help="Watch for status changes in real-time"
)
@click.option(
    "--interval",
    default=5,
    type=int,
    help="Polling interval in seconds for watch mode (default: 5)"
)
@click.pass_obj
def nodepool_status(
    cli_context: "CLIContext",
    nodepool_identifier: str,
    cluster: Optional[str],
    detailed: bool,
    watch: bool,
    interval: int,
) -> None:
    """Show detailed information and status for a nodepool.

    NODEPOOL_IDENTIFIER: NodePool partial ID (8+ chars), full UUID, or name (with --cluster).

    Use --detailed/-d to show all conditions, transition times, and extended
    management configuration.

    \b
    Examples:
        gcphcp nodepools status abc12345
        gcphcp nodepools status abc12345 --detailed
        gcphcp nodepools status abc12345 --watch
        gcphcp nodepools status workers --cluster my-cluster --watch --detailed
    """
    try:
        api_client = cli_context.get_api_client()

        def print_status():
            # Resolve cluster if provided
            cluster_id = None
            if cluster:
                from .clusters import resolve_cluster_identifier
                cluster_id = resolve_cluster_identifier(api_client, cluster)

            # Resolve nodepool identifier (with optional cluster scope)
            nodepool_id = resolve_nodepool_identifier(
                api_client, nodepool_identifier, cluster_id=cluster_id
            )

            # Fetch nodepool details
            nodepool_data = api_client.get(f"/api/v1/nodepools/{nodepool_id}")

            # Use formatter to display
            if cli_context.output_format == "table":
                cli_context.formatter.print_nodepool_status(
                    nodepool_data, nodepool_id, detailed=detailed
                )
            else:
                # For JSON/YAML, always include full data
                cli_context.formatter.print_data({
                    "nodepool_id": nodepool_id,
                    "nodepool": nodepool_data
                })

        if watch:
            if cli_context.output_format != "table":
                raise click.ClickException("Watch mode is only supported in table format")

            try:
                while True:
                    cli_context.console.clear()
                    print_status()
                    cli_context.console.print(
                        f"\n[dim]Refreshing every {interval}s... (Ctrl+C to stop)[/dim]"
                    )
                    time.sleep(interval)
            except KeyboardInterrupt:
                cli_context.console.print("\n[yellow]Watch mode stopped[/yellow]")
        else:
            print_status()

    except click.ClickException:
        raise
    except APIError as e:
        cli_context.console.print(f"[red]API error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@nodepools_group.command("delete")
@click.argument("nodepool_identifier")
@click.option(
    "--cluster",
    help="Cluster identifier to narrow nodepool search (enables name-based lookup)"
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation and delete nodepool with any active nodes"
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt"
)
@click.pass_obj
def delete_nodepool(
    cli_context: "CLIContext",
    nodepool_identifier: str,
    cluster: Optional[str],
    force: bool,
    yes: bool,
) -> None:
    """Delete a nodepool.

    NODEPOOL_IDENTIFIER: NodePool partial ID (8+ chars), full UUID, or name (with --cluster).

    WARNING: This action cannot be undone. All nodes in the nodepool
    will be drained and deleted.

    Use --force to delete nodepools with active nodes and skip confirmation.

    \b
    Examples:
        gcphcp nodepools delete abc12345
        gcphcp nodepools delete abc12345 --yes
        gcphcp nodepools delete workers --cluster my-cluster
        gcphcp nodepools delete workers --cluster my-cluster --force
    """
    try:
        api_client = cli_context.get_api_client()

        # Resolve cluster if provided
        cluster_id = None
        if cluster:
            from .clusters import resolve_cluster_identifier
            cluster_id = resolve_cluster_identifier(api_client, cluster)

        # Resolve nodepool identifier (with optional cluster scope)
        nodepool_id = resolve_nodepool_identifier(
            api_client, nodepool_identifier, cluster_id=cluster_id
        )

        # Fetch nodepool details for confirmation
        nodepool_data = api_client.get(f"/api/v1/nodepools/{nodepool_id}")
        nodepool_name = nodepool_data.get("name", nodepool_id)

        # Get node info for confirmation message
        spec = nodepool_data.get("spec", {})
        replicas = spec.get("replicas") or spec.get("nodeCount") or 0

        # Confirm deletion unless --yes or --force
        if not (yes or force):
            cli_context.console.print(
                f"[yellow]⚠ Warning: You are about to delete nodepool '{nodepool_name}'[/yellow]"
            )
            cli_context.console.print(f"  ID: {nodepool_id}")
            cli_context.console.print(f"  Replicas: {replicas}")
            cli_context.console.print("\n[red]This action cannot be undone![/red]\n")

            # Show force warning if there are active nodes
            if replicas and replicas > 0:
                cli_context.console.print(
                    f"[yellow]This nodepool has {replicas} node(s). "
                    "Use --force to delete anyway.[/yellow]\n"
                )

            if not click.confirm("Do you want to continue?"):
                cli_context.console.print("[yellow]Deletion cancelled[/yellow]")
                return

        if not cli_context.quiet:
            cli_context.console.print(f"[bold cyan]Deleting nodepool '{nodepool_name}'...[/bold cyan]")

        # Delete nodepool with force parameter
        # Always include force=true as API requires it for actual deletion
        params = {"force": "true"}
        api_client.delete(f"/api/v1/nodepools/{nodepool_id}", params=params)

        if not cli_context.quiet:
            cli_context.console.print(
                f"[green]✓[/green] NodePool '{nodepool_name}' deleted successfully"
            )

    except click.ClickException:
        raise
    except APIError as e:
        cli_context.console.print(f"[red]API error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))
