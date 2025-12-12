"""NodePool management commands for GCP HCP CLI."""

import time
from typing import Any, Dict, Optional, Union, TYPE_CHECKING

import click
from rich.panel import Panel

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
    params: Dict[str, Union[int, str]] = {"limit": 100}
    if cluster_id:
        params["clusterId"] = cluster_id

    # Search through nodepools
    try:
        response = api_client.get("/api/v1/nodepools", params=params)
        nodepools = response.get("nodepools") or []

        # Try exact name match first
        name_matches = []
        for nodepool in nodepools:
            if nodepool.get("name") == identifier:
                name_matches.append(
                    (
                        nodepool.get("id"),
                        nodepool.get("name"),
                        nodepool.get("cluster_id") or nodepool.get("clusterId"),
                    )
                )

        if len(name_matches) == 1:
            return name_matches[0][0]  # Return the ID
        elif len(name_matches) > 1:
            # Multiple nodepools with same name across clusters
            match_list = "\n".join(
                [
                    f"  NodePool ID: {id}\n    Cluster ID: {cluster_id}"
                    for id, name, cluster_id in name_matches
                ]
            )
            raise click.ClickException(
                f"Multiple nodepools named '{identifier}' found across "
                f"different clusters:\n\n{match_list}\n\n"
                "Please specify which nodepool using one of:\n"
                f"  - Full or partial nodepool ID: "
                f"gcphcp nodepools <command> {name_matches[0][0][:8]}\n"
                f"  - Nodepool name with --cluster flag: "
                f"gcphcp nodepools <command> {identifier} --cluster <cluster-name>"
            )

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
            "Use 'gcphcp nodepools list --cluster <cluster-id>' "
            "to see available nodepools."
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
        taints.append(
            {"key": key.strip(), "value": value.strip(), "effect": effect.strip()}
        )
    return taints


@click.group("nodepools")
def nodepools_group() -> None:
    """Manage nodepools for clusters."""
    pass


@nodepools_group.command("list")
@click.option(
    "--cluster",
    help=(
        "Optional cluster identifier to filter nodepools "
        "(name, partial ID, or full UUID)"
    ),
)
@click.option(
    "--limit",
    type=int,
    default=50,
    help="Maximum number of nodepools to list (default: 50)",
)
@click.pass_obj
def list_nodepools(
    cli_context: "CLIContext", cluster: Optional[str], limit: int
) -> None:
    """List nodepools across all clusters or for a specific cluster.

    Shows a table of nodepools with their basic information including
    name, status, node counts, and creation date.

    \b
    Examples:
        gcphcp nodepools list
        gcphcp nodepools list --cluster demo08
        gcphcp nodepools list --cluster 3c7f2227
        gcphcp nodepools list --cluster my-cluster --limit 100
    """
    from .clusters import resolve_cluster_identifier

    try:
        api_client = cli_context.get_api_client()

        # Build query parameters
        params: Dict[str, Union[int, str]] = {"limit": limit}

        # Resolve cluster identifier to UUID if provided
        if cluster:
            cluster_id = resolve_cluster_identifier(api_client, cluster)
            params["clusterId"] = cluster_id

        # Fetch nodepools
        response = api_client.get("/api/v1/nodepools", params=params)
        nodepools_data = response.get("nodepools") or []

        # Handle empty list
        if not nodepools_data:
            if not cli_context.quiet:
                if cluster:
                    cli_context.console.print(
                        f"[yellow]No nodepools found for cluster {cluster}[/yellow]"
                    )
                    cli_context.console.print(
                        f"[dim]Create one with:[/dim] gcphcp nodepools create <name> "
                        f"--cluster {cluster} --replicas <N>"
                    )
                else:
                    cli_context.console.print("[yellow]No nodepools found[/yellow]")
                    cli_context.console.print(
                        "[dim]Create one with:[/dim] gcphcp nodepools create <name> "
                        "--cluster <cluster-id> --replicas <N>"
                    )
            return

        # Handle non-table formats
        if cli_context.output_format != "table":
            cli_context.formatter.print_data({"nodepools": nodepools_data})
            return

        # Collect unique cluster IDs to fetch cluster information
        unique_cluster_ids = set()
        for np_data in nodepools_data:
            cluster_id = np_data.get("cluster_id") or np_data.get("clusterId")
            if cluster_id:
                unique_cluster_ids.add(cluster_id)

        # Fetch cluster information for all unique cluster IDs
        cluster_info_map = {}
        for cluster_id in unique_cluster_ids:
            try:
                cluster_data = api_client.get(f"/api/v1/clusters/{cluster_id}")
                cluster_info_map[cluster_id] = {
                    "name": cluster_data.get("name", ""),
                    "project": cluster_data.get("target_project_id")
                    or cluster_data.get("targetProjectId")
                    or "",
                }
            except Exception:
                # If we can't fetch cluster info, use defaults
                cluster_info_map[cluster_id] = {
                    "name": cluster_id[:8],
                    "project": "",
                }

        # Prepare table data
        table_data = []
        for np_data in nodepools_data:
            nodepool = NodePool.from_api_response(np_data)

            # Get cluster info
            cluster_info = cluster_info_map.get(
                nodepool.clusterId, {"name": "", "project": ""}
            )

            table_data.append(
                {
                    "NAME": nodepool.name,
                    "ID": nodepool.id,
                    "STATUS": nodepool.get_display_status(),
                    "CLUSTER": cluster_info["name"],
                    "PROJECT": cluster_info["project"],
                    "CREATED": cli_context.formatter.format_datetime(
                        nodepool.createdAt.isoformat() if nodepool.createdAt else None
                    ),
                }
            )

        # Create table title
        table_title = f"NodePools for cluster {cluster}" if cluster else "All NodePools"

        # Print table using formatter
        cli_context.formatter.print_table(
            data=table_data,
            title=table_title,
            columns=["NAME", "ID", "STATUS", "CLUSTER", "PROJECT", "CREATED"],
        )

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
    help="Cluster identifier (name, partial ID, or full UUID)",
)
@click.option(
    "--replicas", type=int, required=True, help="Number of compute nodes to create"
)
@click.option(
    "--instance-type",
    "--machine-type",
    default="n1-standard-4",
    help="GCP machine type (default: n1-standard-4)",
)
@click.option(
    "--disk-size", type=int, default=128, help="Boot disk size in GB (default: 128)"
)
@click.option(
    "--disk-type",
    type=click.Choice(["pd-standard", "pd-ssd", "pd-balanced"], case_sensitive=False),
    default="pd-standard",
    help="Boot disk type (default: pd-standard)",
)
@click.option(
    "--auto-repair/--no-auto-repair",
    default=True,
    help="Enable auto-repair (default: enabled)",
)
@click.option(
    "--labels",
    multiple=True,
    help="Node labels in key=value format (can be specified multiple times)",
)
@click.option(
    "--taints",
    multiple=True,
    help="Node taints in key=value:effect format (can be specified multiple times)",
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
        nodepool_data: Dict[str, Any] = {
            "name": nodepool_name,
            "cluster_id": cluster_id,
            "spec": {
                "replicas": replicas,
                "platform": {
                    "type": "GCP",
                    "gcp": {
                        "instanceType": instance_type,
                        "rootVolume": {"size": disk_size, "type": disk_type},
                    },
                },
                "management": {"autoRepair": auto_repair, "upgradeType": "Replace"},
            },
        }

        # Add labels and taints if provided
        if parsed_labels:
            nodepool_data["spec"]["platform"]["gcp"]["labels"] = parsed_labels
        if parsed_taints:
            nodepool_data["spec"]["platform"]["gcp"]["taints"] = parsed_taints

        if not cli_context.quiet:
            cli_context.console.print(
                f"[bold cyan]Creating NodePool '{nodepool_name}'...[/bold cyan]"
            )

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
                f"[dim]Use 'gcphcp nodepools status {nodepool_id[:8]}' "
                f"to monitor creation[/dim]",
                title="[bold green]NodePool Created[/bold green]",
                border_style="green",
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
    help="Cluster identifier to narrow nodepool search (enables name-based lookup)",
)
@click.option(
    "--all",
    "-a",
    is_flag=True,
    help="Show all controller status and detailed conditions",
)
@click.option(
    "--watch", "-w", is_flag=True, help="Watch for status changes in real-time"
)
@click.option(
    "--interval",
    default=5,
    type=int,
    help="Polling interval in seconds for watch mode (default: 5)",
)
@click.pass_obj
def nodepool_status(
    cli_context: "CLIContext",
    nodepool_identifier: str,
    cluster: Optional[str],
    all: bool,
    watch: bool,
    interval: int,
) -> None:
    """Show detailed information and status for a nodepool.

    NODEPOOL_IDENTIFIER: NodePool partial ID (8+ chars), full UUID, or name
    (with --cluster).

    Use --all/-a to show all controller status and detailed conditions.

    \b
    Examples:
        gcphcp nodepools status abc12345
        gcphcp nodepools status abc12345 --all
        gcphcp nodepools status abc12345 --watch
        gcphcp nodepools status workers --cluster my-cluster \\
            --watch --all
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

            # Fetch nodepool status from the status endpoint
            status_response = api_client.get(f"/api/v1/nodepools/{nodepool_id}/status")

            # Extract nodepool basic data and status
            nodepool_data = api_client.get(f"/api/v1/nodepools/{nodepool_id}")
            controller_status_data = status_response.get("controller_status", [])

            # Use formatter to display
            if cli_context.output_format == "table":
                cli_context.formatter.print_nodepool_status(nodepool_data, nodepool_id)

                # Display controller status if --all is used
                if all:
                    cli_context.formatter.print_nodepool_controller_status(
                        controller_status_data, nodepool_id
                    )
            else:
                # For JSON/YAML, always include full data
                output_data = {
                    "nodepool_id": nodepool_id,
                    "status": status_response.get("status", {}),
                }
                if all:
                    output_data["controller_status"] = controller_status_data
                cli_context.formatter.print_data(output_data)

        if watch:
            if cli_context.output_format != "table":
                raise click.ClickException(
                    "Watch mode is only supported in table format"
                )

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


@nodepools_group.command("scale")
@click.argument("nodepool_identifier")
@click.option(
    "--cluster",
    help="Cluster identifier to narrow nodepool search (enables name-based lookup)",
)
@click.option(
    "--replicas",
    type=int,
    required=True,
    help="Desired number of nodes in the nodepool",
)
@click.pass_obj
def scale_nodepool(
    cli_context: "CLIContext",
    nodepool_identifier: str,
    cluster: Optional[str],
    replicas: int,
) -> None:
    """Scale a nodepool to the desired number of replicas.

    Similar to 'kubectl scale deployment <name> --replicas=N', this command
    updates the desired replica count for a nodepool.

    NODEPOOL_IDENTIFIER: NodePool partial ID (8+ chars), full UUID, or name
    (with --cluster).

    \b
    Examples:
        gcphcp nodepools scale my-np-01 --replicas 5
        gcphcp nodepools scale abc12345 --replicas 3
        gcphcp nodepools scale workers --cluster my-cluster --replicas 10
    """
    try:
        api_client = cli_context.get_api_client()

        # Validate replicas
        if replicas < 0:
            raise click.ClickException("Replicas must be non-negative")

        # Resolve cluster if provided
        cluster_id = None
        if cluster:
            from .clusters import resolve_cluster_identifier

            cluster_id = resolve_cluster_identifier(api_client, cluster)

        # Resolve nodepool identifier (with optional cluster scope)
        nodepool_id = resolve_nodepool_identifier(
            api_client, nodepool_identifier, cluster_id=cluster_id
        )

        # Fetch current nodepool to get the current spec
        nodepool_data = api_client.get(f"/api/v1/nodepools/{nodepool_id}")
        nodepool_name = nodepool_data.get("name") or nodepool_id
        current_spec = nodepool_data.get("spec", {})
        current_replicas = current_spec.get("replicas") or current_spec.get(
            "nodeCount", 0
        )

        if not cli_context.quiet:
            cli_context.console.print(
                f"[bold cyan]Scaling nodepool '{nodepool_name}' "
                f"from {current_replicas} to {replicas} replicas...[/bold cyan]"
            )

        # Update only the replicas field in the spec
        updated_spec = current_spec.copy()
        updated_spec["replicas"] = replicas

        # Send PUT request with updated spec
        update_payload = {"spec": updated_spec}
        api_client.put(f"/api/v1/nodepools/{nodepool_id}", json_data=update_payload)

        if not cli_context.quiet:
            cli_context.console.print(
                f"[green]✓[/green] NodePool '{nodepool_name}' "
                f"scaled to {replicas} replicas"
            )
            cli_context.console.print(
                f"[dim]Use 'gcphcp nodepools status {nodepool_id[:8]}' "
                f"to monitor the scaling progress[/dim]"
            )
        else:
            # In quiet mode, print the nodepool ID
            cli_context.console.print(nodepool_id)

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


@nodepools_group.command("delete")
@click.argument("nodepool_identifier")
@click.option(
    "--cluster",
    help="Cluster identifier to narrow nodepool search (enables name-based lookup)",
)
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation and delete nodepool with any active nodes",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt")
@click.pass_obj
def delete_nodepool(
    cli_context: "CLIContext",
    nodepool_identifier: str,
    cluster: Optional[str],
    force: bool,
    yes: bool,
) -> None:
    """Delete a nodepool.

    NODEPOOL_IDENTIFIER: NodePool partial ID (8+ chars), full UUID, or name
    (with --cluster).

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
        nodepool_name = nodepool_data.get("name") or nodepool_id

        # Get node info for confirmation message
        spec = nodepool_data.get("spec", {})
        replicas = spec.get("replicas") or spec.get("nodeCount") or 0

        # Confirm deletion unless --yes or --force
        if not (yes or force):
            cli_context.console.print(
                f"[yellow]⚠ Warning: You are about to delete nodepool "
                f"'{nodepool_name}'[/yellow]"
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
            cli_context.console.print(
                f"[bold cyan]Deleting nodepool '{nodepool_name}'...[/bold cyan]"
            )

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
