"""Cluster management commands for GCP HCP CLI."""

import click
from typing import Dict, Union, TYPE_CHECKING
from rich.panel import Panel
from rich.text import Text

from ...client.exceptions import APIError, ResourceNotFoundError

if TYPE_CHECKING:
    from ..main import CLIContext


def resolve_cluster_identifier(api_client, identifier: str) -> str:
    """Resolve cluster identifier (name, partial ID, or full ID) to full cluster ID.

    Args:
        api_client: API client instance
        identifier: Cluster name, partial ID (>=8 chars), or full ID

    Returns:
        Full cluster ID (UUID)

    Raises:
        click.ClickException: If no cluster found or multiple matches
    """
    # If it looks like a full UUID, try it directly first
    if len(identifier) == 36 and identifier.count("-") == 4:
        try:
            # Test if it exists by fetching it
            api_client.get(f"/api/v1/clusters/{identifier}")
            return identifier
        except ResourceNotFoundError:
            pass

    # Search through all clusters
    try:
        response = api_client.get("/api/v1/clusters", params={"limit": 100})
        clusters = response.get("clusters") or []

        # Try exact name match first
        for cluster in clusters:
            if cluster.get("name") == identifier:
                return cluster.get("id")

        # Try partial ID match (case-insensitive)
        identifier_lower = identifier.lower()
        matches = []
        for cluster in clusters:
            cluster_id = cluster.get("id", "")
            if cluster_id.lower().startswith(identifier_lower):
                matches.append((cluster.get("id"), cluster.get("name")))

        if len(matches) == 1:
            return matches[0][0]  # Return the ID
        elif len(matches) > 1:
            match_list = "\n".join([f"  {id} ({name})" for id, name in matches])
            raise click.ClickException(
                f"Multiple clusters match '{identifier}':\n{match_list}\n"
                "Please provide a more specific identifier."
            )

        # No matches found
        raise click.ClickException(
            f"No cluster found with identifier '{identifier}'. "
            "Use 'gcphcp clusters list' to see available clusters."
        )

    except APIError as e:
        raise click.ClickException(f"Failed to search clusters: {e}")
    except ResourceNotFoundError:
        raise click.ClickException(f"Cluster '{identifier}' not found.")


@click.group("clusters")
def clusters_group() -> None:
    """Manage clusters."""
    pass


@clusters_group.command("list")
@click.option(
    "--limit",
    type=int,
    default=10,
    help="Maximum number of clusters to list",
)
@click.option(
    "--offset",
    type=int,
    default=0,
    help="Number of clusters to skip (for pagination)",
)
@click.option(
    "--status",
    type=click.Choice(
        ["Pending", "Progressing", "Ready", "Failed"], case_sensitive=False
    ),
    help="Filter clusters by status",
)
@click.pass_obj
def list_clusters(
    cli_context: "CLIContext", limit: int, offset: int, status: str
) -> None:
    """List clusters in the current project.

    Shows a table of clusters with their basic information including
    name, status, created date, and other key details.
    """
    try:
        # Build query parameters
        params: Dict[str, Union[int, str]] = {
            "limit": limit,
            "offset": offset,
        }
        if status:
            params["status"] = status

        # Make API request
        api_client = cli_context.get_api_client()
        response = api_client.get("/api/v1/clusters", params=params)

        clusters = response.get("clusters") or []
        total = response.get("total", len(clusters))

        if not clusters:
            if not cli_context.quiet:
                message = "No clusters found"
                if status:
                    message += f" with status '{status}'"
                cli_context.console.print(f"[yellow]{message}.[/yellow]")
            return

        # Format output
        if cli_context.output_format == "table":
            # Prepare table data with full IDs
            table_data = []
            for cluster in clusters:
                table_data.append(
                    {
                        "NAME": cluster.get("name", ""),
                        "ID": cluster.get("id", ""),  # Show full ID
                        "STATUS": cluster.get("status", {}).get("phase", "Unknown"),
                        "PROJECT": cluster.get("target_project_id", ""),
                        "CREATED": cli_context.formatter.format_datetime(
                            cluster.get("created_at")
                        ),
                    }
                )

            cli_context.formatter.print_table(
                data=table_data,
                title=f"Clusters ({len(clusters)}/{total})",
                columns=["NAME", "ID", "STATUS", "PROJECT", "CREATED"],
            )
        else:
            # Use raw format for non-table outputs
            cli_context.formatter.print_data(clusters)

        # Show pagination info if needed
        if not cli_context.quiet and total > limit:
            remaining = total - offset - len(clusters)
            if remaining > 0:
                cli_context.console.print(
                    f"[dim]Showing {len(clusters)} of {total} clusters. "
                    f"Use --offset {offset + limit} to see more.[/dim]"
                )

    except APIError as e:
        cli_context.console.print(f"[red]API error: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@clusters_group.command("status")
@click.argument("cluster_identifier")
@click.option(
    "--watch",
    "-w",
    is_flag=True,
    help="Watch for status changes in real-time",
)
@click.option(
    "--interval",
    default=5,
    type=int,
    help="Polling interval in seconds for watch mode (default: 5)",
)
@click.option(
    "--all",
    "-a",
    is_flag=True,
    help="Show additional detailed controller status and resource information",
)
@click.pass_obj
def cluster_status(
    cli_context: "CLIContext",
    cluster_identifier: str,
    watch: bool,
    interval: int,
    all: bool,
) -> None:
    """Show detailed information and status for a cluster.

    Displays comprehensive cluster details including current status, conditions,
    platform configuration, and metadata in a well-formatted, color-coded view.

    Use --all/-a to include additional controller status, resource details,
    and hosted cluster conditions from the underlying Hypershift controllers.

    CLUSTER_IDENTIFIER: Cluster name, partial ID (8+ chars), or full UUID.

    Examples:
      gcphcp clusters status demo08
      gcphcp clusters status demo08 --all
      gcphcp clusters status 3c7f2227 --watch --interval 3
      gcphcp clusters status demo08 --watch --all
    """
    import time
    from ...client.exceptions import ResourceNotFoundError, APIError

    # Resolve identifier once at the beginning
    try:
        api_client = cli_context.get_api_client()
        cluster_id = resolve_cluster_identifier(api_client, cluster_identifier)
    except click.ClickException:
        raise

    def print_status():
        try:
            cluster = api_client.get(f"/api/v1/clusters/{cluster_id}")

            # Fetch additional controller status if --all flag is used
            controller_status_data = None
            if all:
                try:
                    controller_status_data = api_client.get(
                        f"/api/v1/clusters/{cluster_id}/status"
                    )
                except APIError as e:
                    # If status endpoint is not available, show warning but continue
                    if not cli_context.quiet:
                        cli_context.console.print(
                            f"[yellow]Warning: Could not fetch status: {e}[/yellow]"
                        )

            if cli_context.output_format == "table":
                cli_context.formatter.print_cluster_status(cluster, cluster_id)

                # Display additional controller status in table format
                if all and controller_status_data:
                    cli_context.formatter.print_controller_status(
                        controller_status_data, cluster_id
                    )
            else:
                # For JSON/YAML, show comprehensive data
                status_data = {
                    "cluster_id": cluster_id,
                    "cluster_name": cluster.get("name", "Unknown"),
                    "status": cluster.get("status", {}),
                    "last_checked": time.strftime(
                        "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
                    ),
                }

                # Include controller status data if --all is used
                if all and controller_status_data:
                    status_data["controller_status"] = controller_status_data.get(
                        "controller_status", []
                    )
                    status_data["detailed_status"] = controller_status_data.get(
                        "status", {}
                    )

                cli_context.formatter.print_data(status_data)

        except ResourceNotFoundError:
            cli_context.console.print(f"[red]Cluster '{cluster_id}' not found.[/red]")
            raise click.ClickException(f"Cluster not found: {cluster_id}")
        except APIError as e:
            cli_context.console.print(f"[red]API error: {e}[/red]")
            raise click.ClickException(str(e))

    if watch:
        cli_context.console.print(
            "[cyan]Watching cluster status (press Ctrl+C to stop)...[/cyan]\n"
        )
        try:
            while True:
                if cli_context.output_format == "table":
                    # Clear screen for table format
                    cli_context.console.clear()
                    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
                    cli_context.console.print(f"[cyan]{timestamp}[/cyan]")

                print_status()

                if cli_context.output_format != "table":
                    cli_context.console.print(
                        f"\n[dim]Next update in {interval} seconds...[/dim]"
                    )

                time.sleep(interval)
        except KeyboardInterrupt:
            cli_context.console.print("\n[yellow]Status monitoring stopped.[/yellow]")
    else:
        print_status()


@clusters_group.command("create")
@click.argument("cluster_name")
@click.option(
    "--project",
    help="Target project ID (overrides default)",
)
@click.option(
    "--description",
    help="Description for the cluster",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Show what would be created without actually creating",
)
@click.pass_obj
def create_cluster(
    cli_context: "CLIContext",
    cluster_name: str,
    project: str,
    description: str,
    dry_run: bool,
) -> None:
    """Create a new cluster.

    CLUSTER_NAME: Name for the new cluster (must be DNS-compatible).
    """
    try:
        # Use project from command line or config
        target_project = project or cli_context.config.get("default_project")
        if not target_project:
            cli_context.console.print(
                "[red]Project ID required. Use --project or set default_project.[/red]"
            )
            raise click.ClickException("Project ID required")

        # Prepare cluster data
        cluster_data = {
            "name": cluster_name,
            "target_project_id": target_project,
        }
        if description:
            cluster_data["description"] = description

        if dry_run:
            # Show what would be created
            cli_context.console.print("[yellow]Dry run - would create:[/yellow]")
            cli_context.formatter.print_data(cluster_data)
            return

        # Confirm creation
        if not cli_context.quiet:
            cli_context.console.print(
                f"Creating cluster '{cluster_name}' in project '{target_project}'..."
            )

        # Make API request
        api_client = cli_context.get_api_client()
        cluster = api_client.post("/api/v1/clusters", json_data=cluster_data)

        if not cli_context.quiet:
            success_text = Text()
            success_text.append(
                "✓ Cluster created successfully!\n\n", style="green bold"
            )
            success_text.append(f"Name: {cluster.get('name')}\n", style="bright_blue")
            success_text.append(f"ID: {cluster.get('id')}\n", style="dim")
            success_text.append(
                f"Status: {cluster.get('status', {}).get('phase', 'Unknown')}",
                style="dim",
            )

            panel = Panel(
                success_text,
                title="[green]Cluster Created[/green]",
                border_style="green",
            )
            cli_context.console.print(panel)
        else:
            cli_context.formatter.print_data(cluster)

    except APIError as e:
        cli_context.console.print(f"[red]Failed to create cluster: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


@clusters_group.command("delete")
@click.argument("cluster_identifier")
@click.option(
    "--force",
    is_flag=True,
    help="Skip safety checks and delete cluster with any active resources",
)
@click.option(
    "--yes",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_obj
def delete_cluster(
    cli_context: "CLIContext", cluster_identifier: str, force: bool, yes: bool
) -> None:
    """Delete a cluster.

    CLUSTER_IDENTIFIER: Cluster name, partial ID (8+ chars), or full UUID.

    WARNING: This action cannot be undone. The cluster and all its
    resources will be permanently deleted.

    Examples:
      gcphcp clusters delete demo08
      gcphcp clusters delete 3c7f2227 --yes
    """
    try:
        # Resolve identifier and get cluster info for confirmation
        api_client = cli_context.get_api_client()
        cluster_id = resolve_cluster_identifier(api_client, cluster_identifier)
        cluster = api_client.get(f"/api/v1/clusters/{cluster_id}")
        cluster_name = cluster.get("name", cluster_id)

        # Confirm deletion
        if not yes and not cli_context.quiet:
            cli_context.console.print(
                f"[red]About to delete cluster '{cluster_name}' ({cluster_id}).[/red]"
            )
            if not click.confirm("This action cannot be undone. Continue?"):
                cli_context.console.print("Deletion cancelled.")
                return

        # Prepare delete parameters
        # Always include force=true as API requires it for actual deletion
        params = {"force": "true"}

        # Note: The --force flag is now about bypassing confirmation and
        # deleting clusters with active resources, not about the API parameter

        if not cli_context.quiet:
            cli_context.console.print(f"Deleting cluster '{cluster_name}'...")

        # Make delete request
        api_client.delete(f"/api/v1/clusters/{cluster_id}", params=params)

        if not cli_context.quiet:
            cli_context.console.print(
                f"[green]✓[/green] Cluster '{cluster_name}' deleted successfully."
            )

    except click.ClickException:
        # Re-raise click exceptions (from resolve_cluster_identifier)
        raise
    except APIError as e:
        cli_context.console.print(f"[red]Failed to delete cluster: {e}[/red]")
        raise click.ClickException(str(e))
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))
