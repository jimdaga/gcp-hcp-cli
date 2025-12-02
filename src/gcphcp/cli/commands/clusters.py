"""Cluster management commands for GCP HCP CLI."""

import base64
import json
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Union, TYPE_CHECKING

import click
from rich.panel import Panel
from rich.text import Text

from ...client.exceptions import APIError, ResourceNotFoundError

if TYPE_CHECKING:
    from ..main import CLIContext


@dataclass
class WIFSetupResult:
    """Result of WIF infrastructure setup (automatic or manual)."""

    wif_spec: Dict
    signing_key_base64: str
    issuer_url: str
    wif_config: Optional[Dict] = (
        None  # Raw config from hypershift (automatic mode only)
    )


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


# =============================================================================
# WIF Setup Helper Functions
# =============================================================================


def _setup_wif_automatic(
    cli_context: "CLIContext",
    infra_id: str,
    project_id: str,
) -> WIFSetupResult:
    """Setup WIF infrastructure automatically using hypershift CLI.

    This mode:
    1. Generates an RSA keypair for service account signing
    2. Provisions WIF infrastructure via 'hypershift create iam gcp'
    3. Returns the WIF configuration for cluster creation

    Args:
        cli_context: CLI context for console output and config
        infra_id: Infrastructure ID for WIF resources
        project_id: GCP project ID

    Returns:
        WIFSetupResult with all necessary WIF configuration

    Raises:
        click.ClickException: If keypair generation or IAM provisioning fails
    """
    from ...utils.hypershift import (
        create_iam_gcp,
        validate_wif_config,
        wif_config_to_cluster_spec,
        HypershiftError,
    )
    from ...utils.crypto import generate_cluster_keypair

    keypair_result = None

    try:
        # Step 1: Generate keypair
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print("[bold cyan]Step 1: Generate Keypair[/bold cyan]")

        keypair_result = generate_cluster_keypair()

        if not cli_context.quiet:
            cli_context.console.print("[green]✓[/green] Keypair generated successfully")
            cli_context.console.print(f"[dim]  kid: {keypair_result.kid}[/dim]")

        # Step 2: Setup WIF Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 2: Setup WIF Infrastructure[/bold cyan]"
            )

        wif_config = create_iam_gcp(
            infra_id=infra_id,
            project_id=project_id,
            oidc_jwks_file=keypair_result.jwks_file_path,
            console=cli_context.console if not cli_context.quiet else None,
            config=cli_context.config,
        )

        # Validate the output
        if not validate_wif_config(wif_config):
            raise click.ClickException(
                "Invalid WIF configuration returned from hypershift"
            )

        # Convert to cluster spec format
        wif_spec = wif_config_to_cluster_spec(wif_config)

        return WIFSetupResult(
            wif_spec=wif_spec,
            signing_key_base64=keypair_result.private_key_pem_base64,
            issuer_url=f"https://hypershift-{infra_id}-oidc",
            wif_config=wif_config,
        )

    except HypershiftError as e:
        raise click.ClickException(f"Failed to setup infrastructure: {e}")
    except Exception as e:
        raise click.ClickException(f"Failed to generate keypair: {e}")
    finally:
        # Clean up temporary JWKS file
        if keypair_result:
            keypair_result.cleanup()


def _setup_wif_manual(
    cli_context: "CLIContext",
    iam_config_file: str,
    signing_key_file: str,
    fallback_infra_id: str,
) -> Tuple[WIFSetupResult, str]:
    """Setup WIF configuration from pre-generated files.

    This mode uses output files from 'gcphcp infra create':
    - IAM config JSON with pool/provider IDs and service accounts
    - PEM-encoded RSA private key for service account signing

    Args:
        cli_context: CLI context for console output
        iam_config_file: Path to IAM/WIF configuration JSON
        signing_key_file: Path to PEM-encoded RSA private key
        fallback_infra_id: Infra ID to use if not found in config

    Returns:
        Tuple of (WIFSetupResult, infra_id) - infra_id may come from config file

    Raises:
        click.ClickException: If files cannot be read or parsed
    """
    # Load IAM/WIF configuration from file
    try:
        with open(iam_config_file, "r") as f:
            wif_config = json.load(f)

        # Extract values from IAM config file
        wif_project_number = wif_config.get("projectNumber")
        wif_pool_id = wif_config.get("workloadIdentityPool", {}).get("poolId")
        wif_provider_id = wif_config.get("workloadIdentityPool", {}).get("providerId")
        wif_cp_sa_email = wif_config.get("serviceAccounts", {}).get("ctrlplane-op")
        wif_nodepool_sa_email = wif_config.get("serviceAccounts", {}).get(
            "nodepool-mgmt"
        )

        # Get infra ID from config or use fallback
        infra_id = wif_config.get("infraId") or fallback_infra_id

        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Loaded IAM configuration from file[/bold cyan]"
            )
            cli_context.console.print(f"[dim]  File: {iam_config_file}[/dim]")
            cli_context.console.print(f"[dim]  Infra ID: {infra_id}[/dim]")
            cli_context.console.print(f"[dim]  Pool ID: {wif_pool_id}[/dim]")
            cli_context.console.print(f"[dim]  Provider ID: {wif_provider_id}[/dim]")

    except Exception as e:
        raise click.ClickException(f"Failed to load IAM config file: {e}")

    # Read and encode the signing key file
    try:
        with open(signing_key_file, "r") as f:
            signing_key_pem = f.read()
        signing_key_base64 = base64.b64encode(signing_key_pem.encode("utf-8")).decode(
            "utf-8"
        )
    except Exception as e:
        raise click.ClickException(f"Failed to read signing key file: {e}")

    # Build WIF spec from IAM config
    wif_spec = {
        "projectNumber": wif_project_number,
        "poolID": wif_pool_id,
        "providerID": wif_provider_id,
        "serviceAccountsRef": {
            "controlPlaneEmail": wif_cp_sa_email,
            "nodePoolEmail": wif_nodepool_sa_email,
        },
    }

    wif_result = WIFSetupResult(
        wif_spec=wif_spec,
        signing_key_base64=signing_key_base64,
        issuer_url=f"https://hypershift-{infra_id}-oidc",
    )

    return wif_result, infra_id


def _build_cluster_spec(
    cluster_name: str,
    project_id: str,
    region: str,
    infra_id: str,
    wif_result: WIFSetupResult,
    description: Optional[str] = None,
) -> Dict:
    """Build the cluster data payload for API submission.

    Args:
        cluster_name: Name for the cluster
        project_id: Target GCP project ID
        region: GCP region for the cluster
        infra_id: Infrastructure ID for the cluster
        wif_result: WIF setup result with WIF configuration
        description: Optional cluster description

    Returns:
        Complete cluster data dict ready for API submission
    """
    cluster_data = {
        "name": cluster_name,
        "target_project_id": project_id,
        "spec": {
            "infraID": infra_id,
            "issuerURL": wif_result.issuer_url,
            "serviceAccountSigningKey": wif_result.signing_key_base64,
            "platform": {
                "type": "GCP",
                "gcp": {
                    "projectID": project_id,
                    "region": region,
                    "workloadIdentity": wif_result.wif_spec,
                },
            },
        },
    }

    if description:
        cluster_data["description"] = description

    return cluster_data


# =============================================================================
# CLI Commands
# =============================================================================


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
    "--infra-id",
    help="Infrastructure ID for infrastructure setup (defaults to cluster name)",
)
@click.option(
    "--region",
    default="us-central1",
    help="GCP region for the cluster (default: us-central1)",
)
@click.option(
    "--setup-infra",
    is_flag=True,
    help="Automatically setup WIF infrastructure (keypair + IAM)",
)
@click.option(
    "--iam-config-file",
    type=click.Path(exists=True),
    help="Path to IAM/WIF config JSON from 'gcphcp infra create'",
)
@click.option(
    "--signing-key-file",
    type=click.Path(exists=True),
    help="Path to PEM-encoded RSA private key for SA signing (manual mode)",
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
    infra_id: str,
    region: str,
    setup_infra: bool,
    iam_config_file: str,
    signing_key_file: str,
    dry_run: bool,
) -> None:
    """Create a new cluster with WIF configuration.

    CLUSTER_NAME: Name for the new cluster (must be DNS-compatible).

    Two modes of operation:

    1. Automatic mode (--setup-infra): CLI automatically generates keypair
       and provisions required infrastructure (WIF, Network, etc.).

    2. Manual mode: Use output files from 'gcphcp infra create' via
       --iam-config-file and --signing-key-file options.

    Examples:

      # Automatic infrastructure setup
      gcphcp clusters create my-cluster --project my-project --setup-infra

      # Manual mode using infra create output files
      gcphcp clusters create my-cluster --project my-project \\
        --iam-config-file my-infra-iam-config.json \\
        --signing-key-file my-infra-signing-key.pem
    """
    try:
        # Resolve project ID
        target_project = project or cli_context.config.get("default_project")
        if not target_project:
            cli_context.console.print(
                "[red]Project ID required. Use --project or set default_project.[/red]"
            )
            raise click.ClickException("Project ID required")

        # Determine infra ID (defaults to cluster name)
        effective_infra_id = infra_id or cluster_name

        # =================================================================
        # Mode Selection: Automatic vs Manual WIF Setup
        # =================================================================

        if setup_infra:
            # Automatic mode: generate keypair and provision WIF infrastructure
            wif_result = _setup_wif_automatic(
                cli_context=cli_context,
                infra_id=effective_infra_id,
                project_id=target_project,
            )
            # In automatic mode, infra_id is the input we provided
            resolved_infra_id = effective_infra_id

            if not cli_context.quiet:
                cli_context.console.print()
                cli_context.console.print(
                    "[bold cyan]Step 3: Creating Cluster[/bold cyan]"
                )
        else:
            # Manual mode: use pre-generated files from 'gcphcp infra create'
            if not iam_config_file:
                cli_context.console.print(
                    "[red]Error: Manual mode requires --iam-config-file[/red]"
                )
                raise click.ClickException(
                    "Either use --setup-infra for automatic setup, "
                    "or provide --iam-config-file for manual mode"
                )

            if not signing_key_file:
                cli_context.console.print(
                    "[red]Error: Manual mode requires --signing-key-file[/red]"
                )
                raise click.ClickException(
                    "--signing-key-file is required for manual mode"
                )

            # Manual mode may extract infra_id from config file
            wif_result, resolved_infra_id = _setup_wif_manual(
                cli_context=cli_context,
                iam_config_file=iam_config_file,
                signing_key_file=signing_key_file,
                fallback_infra_id=effective_infra_id,
            )

            if not cli_context.quiet:
                cli_context.console.print()
                cli_context.console.print(
                    "[bold cyan]Creating Cluster with Manual Configuration[/bold cyan]"
                )

        # =================================================================
        # Build Cluster Spec and Submit to API
        # =================================================================

        cluster_data = _build_cluster_spec(
            cluster_name=cluster_name,
            project_id=target_project,
            region=region,
            infra_id=resolved_infra_id,
            wif_result=wif_result,
            description=description,
        )

        if dry_run:
            cli_context.console.print("[yellow]Dry run - would create:[/yellow]")
            cli_context.formatter.print_data(cluster_data)
            if setup_infra and wif_result.wif_config:
                cli_context.console.print(
                    "\n[yellow]WIF Configuration (from hypershift):[/yellow]"
                )
                cli_context.formatter.print_data(wif_result.wif_config)
            return

        if not cli_context.quiet:
            cli_context.console.print(
                f"Creating cluster '{cluster_name}' in project '{target_project}'..."
            )
            if cli_context.verbosity >= 2:
                cli_context.console.print("[dim]Debug - Sending cluster_data:[/dim]")
                cli_context.console.print(
                    f"[dim]{json.dumps(cluster_data, indent=2)}[/dim]"
                )

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
