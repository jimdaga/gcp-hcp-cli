"""Cluster management commands for GCP HCP CLI."""

import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

import click
from rich.panel import Panel
from rich.text import Text

from ...client.exceptions import APIError, ResourceNotFoundError

if TYPE_CHECKING:
    from ..main import CLIContext


@dataclass
class IAMConfigValues:
    """Extracted values from IAM configuration."""

    project_id: Optional[str] = None
    infra_id: Optional[str] = None
    wif_spec: Optional[Dict] = None  # Transformed spec for cluster API


def extract_iam_config_values(
    iam_config: Dict,
    cli_context: Optional["CLIContext"] = None,
    source_label: str = "IAM config",
) -> IAMConfigValues:
    """Extract IAM configuration values from a config dict.

    Args:
        iam_config: Dictionary containing IAM configuration
        cli_context: Optional CLI context for console output
        source_label: Label for output messages

    Returns:
        IAMConfigValues with extracted values including wif_spec for cluster API
    """
    from ...utils.hypershift import iam_config_to_wif_spec

    values = IAMConfigValues(
        project_id=iam_config.get("projectId"),
        infra_id=iam_config.get("infraId"),
        wif_spec=iam_config_to_wif_spec(iam_config),
    )

    if cli_context and not cli_context.quiet:
        cli_context.console.print()
        cli_context.console.print(
            f"[bold cyan]Loaded IAM configuration from {source_label}[/bold cyan]"
        )
        if values.infra_id:
            cli_context.console.print(f"[dim]  Infra ID: {values.infra_id}[/dim]")
        if values.project_id:
            cli_context.console.print(f"[dim]  Project ID: {values.project_id}[/dim]")

    return values


@dataclass
class InfraConfigValues:
    """Extracted values from infrastructure configuration."""

    network: Optional[str] = None
    subnet: Optional[str] = None
    region: Optional[str] = None
    infra_id: Optional[str] = None
    project_id: Optional[str] = None


def extract_infra_config_values(
    infra_config: Dict,
    cli_context: Optional["CLIContext"] = None,
    source_label: str = "infra config",
) -> InfraConfigValues:
    """Extract infrastructure values from a config dict.

    This provides common handling for infra config from both:
    - --infra-config-file (loaded from file)
    - --setup-infra (returned from hypershift create infra gcp)

    Args:
        infra_config: Dictionary containing infrastructure configuration
        cli_context: Optional CLI context for console output
        source_label: Label for output messages (e.g., "file" or "infra setup")

    Returns:
        InfraConfigValues with extracted values
    """
    values = InfraConfigValues(
        network=infra_config.get("networkName"),
        subnet=infra_config.get("subnetName"),
        region=infra_config.get("region"),
        infra_id=infra_config.get("infraId"),
        project_id=infra_config.get("projectId"),
    )

    if cli_context and not cli_context.quiet:
        cli_context.console.print()
        cli_context.console.print(
            f"[bold cyan]Loaded infra config from {source_label}[/bold cyan]"
        )
        if values.infra_id:
            cli_context.console.print(f"[dim]  Infra ID: {values.infra_id}[/dim]")
        if values.region:
            cli_context.console.print(f"[dim]  Region: {values.region}[/dim]")
        if values.network:
            cli_context.console.print(f"[dim]  Network: {values.network}[/dim]")
        if values.subnet:
            cli_context.console.print(f"[dim]  Subnet: {values.subnet}[/dim]")

    return values


@dataclass
class ClusterConfig:
    """Configuration for cluster creation (from --setup-infra or config files)."""

    wif_spec: Dict
    signing_key_base64: str
    issuer_url: str
    infra_id: str
    project_id: str
    region: Optional[str] = None
    network: Optional[str] = None
    subnet: Optional[str] = None


def _setup_cluster_infra(
    cli_context: "CLIContext",
    infra_id: str,
    project_id: str,
    region: str,
    vpc_cidr: str = "10.0.0.0/24",
) -> ClusterConfig:
    """Setup infrastructure using hypershift CLI (--setup-infra mode).

    This mode:
    1. Generates an RSA keypair for service account signing
    2. Provisions WIF infrastructure via 'hypershift create iam gcp'
    3. Provisions network infrastructure via 'hypershift create infra gcp'
    4. Returns the complete configuration for cluster creation

    Args:
        cli_context: CLI context for console output and config
        infra_id: Infrastructure ID for resources
        project_id: GCP project ID
        region: GCP region for network resources
        vpc_cidr: CIDR block for the subnet

    Returns:
        ClusterConfig with all necessary configuration

    Raises:
        click.ClickException: If any provisioning step fails
    """
    from ...utils.hypershift import (
        create_iam_gcp,
        create_infra_gcp,
        validate_iam_config,
        validate_infra_config,
        iam_config_to_wif_spec,
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

        # Step 2: Setup IAM Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 2: Setup IAM Infrastructure[/bold cyan]"
            )

        iam_config = create_iam_gcp(
            infra_id=infra_id,
            project_id=project_id,
            oidc_jwks_file=keypair_result.jwks_file_path,
            console=cli_context.console if not cli_context.quiet else None,
            config=cli_context.config,
        )

        # Validate the output
        if not validate_iam_config(iam_config):
            raise click.ClickException(
                "Invalid IAM configuration returned from hypershift"
            )

        # Step 3: Setup Network Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 3: Setup Network Infrastructure[/bold cyan]"
            )

        infra_config = create_infra_gcp(
            infra_id=infra_id,
            project_id=project_id,
            region=region,
            vpc_cidr=vpc_cidr,
            console=cli_context.console if not cli_context.quiet else None,
            config=cli_context.config,
        )

        # Validate the output
        if not validate_infra_config(infra_config):
            raise click.ClickException(
                "Invalid infrastructure configuration returned from hypershift"
            )

        # Convert to cluster spec format and build result
        wif_spec = iam_config_to_wif_spec(iam_config)

        # Values are guaranteed by validate_iam_config/validate_infra_config
        return ClusterConfig(
            wif_spec=wif_spec,
            signing_key_base64=keypair_result.private_key_pem_base64,
            issuer_url=f"https://hypershift-{infra_id}-oidc",
            infra_id=str(iam_config.get("infraId")),
            project_id=str(iam_config.get("projectId")),
            region=str(infra_config.get("region")),
            network=str(infra_config.get("networkName")),
            subnet=str(infra_config.get("subnetName")),
        )

    except HypershiftError as e:
        raise click.ClickException(f"Failed to setup infrastructure: {e}")
    except Exception as e:
        raise click.ClickException(f"Failed to generate keypair: {e}")
    finally:
        # Clean up temporary JWKS file
        if keypair_result:
            keypair_result.cleanup()


def _load_cluster_config(
    cli_context: "CLIContext",
    signing_key_file: str,
    iam_config_file: str,
    infra_config_file: Optional[str] = None,
) -> ClusterConfig:
    """Build cluster configuration from pre-generated config files.

    This function handles all config file loading, validation, and extraction
    when using pre-generated config files.

    Args:
        cli_context: CLI context for console output
        iam_config_file: Path to IAM/WIF configuration JSON (required)
        signing_key_file: Path to PEM-encoded RSA private key (required)
        infra_config_file: Path to infrastructure configuration JSON (optional)

    Returns:
        ClusterConfig with all extracted values

    Raises:
        click.ClickException: If files cannot be read, parsed, or validated
    """
    from ...utils.hypershift import (
        validate_iam_config,
        validate_infra_config,
    )

    # =================================================================
    # Load and validate IAM config file (required)
    # =================================================================
    try:
        with open(iam_config_file, "r") as f:
            iam_config = json.load(f)

        if not validate_iam_config(iam_config):
            raise click.ClickException(
                f"Invalid IAM configuration in {iam_config_file}. "
                "Required fields: projectId, projectNumber, infraId, "
                "workloadIdentityPool, serviceAccounts"
            )

        iam_values = extract_iam_config_values(
            iam_config,
            cli_context=cli_context if not cli_context.quiet else None,
            source_label=f"file ({iam_config_file})",
        )

    except click.ClickException:
        raise
    except Exception as e:
        raise click.ClickException(f"Failed to load IAM config file: {e}")

    infra_values = None

    # =================================================================
    # Load and validate infra config file (if provided)
    # =================================================================
    if infra_config_file:
        try:
            with open(infra_config_file, "r") as f:
                infra_config = json.load(f)

            if not validate_infra_config(infra_config):
                raise click.ClickException(
                    f"Invalid infra config in {infra_config_file}. "
                    "Required: projectId, infraId, region, networkName, subnetName"
                )

            infra_values = extract_infra_config_values(
                infra_config,
                cli_context=cli_context if not cli_context.quiet else None,
                source_label=f"file ({infra_config_file})",
            )

        except click.ClickException:
            raise
        except Exception as e:
            raise click.ClickException(f"Failed to load infra config file: {e}")

    # =================================================================
    # Cross-validate if both config files provided
    # =================================================================
    if infra_values:
        mismatches = []
        if iam_values.project_id and infra_values.project_id:
            if iam_values.project_id != infra_values.project_id:
                mismatches.append(
                    f"projectId: IAM config has '{iam_values.project_id}', "
                    f"infra config has '{infra_values.project_id}'"
                )
        if iam_values.infra_id and infra_values.infra_id:
            if iam_values.infra_id != infra_values.infra_id:
                mismatches.append(
                    f"infraId: IAM config has '{iam_values.infra_id}', "
                    f"infra config has '{infra_values.infra_id}'"
                )
        if mismatches:
            raise click.ClickException(
                "Mismatch between IAM config and infra config files:\n  - "
                + "\n  - ".join(mismatches)
            )

    # =================================================================
    # Read and encode signing key file
    # =================================================================
    try:
        with open(signing_key_file, "r") as f:
            signing_key_pem = f.read()
        signing_key_base64 = base64.b64encode(signing_key_pem.encode("utf-8")).decode(
            "utf-8"
        )
    except Exception as e:
        raise click.ClickException(f"Failed to read signing key file: {e}")

    # =================================================================
    # Build result with values from config files
    # =================================================================
    # Values are guaranteed by validate_iam_config
    assert iam_values.infra_id is not None
    assert iam_values.project_id is not None
    assert iam_values.wif_spec is not None

    return ClusterConfig(
        wif_spec=iam_values.wif_spec,
        signing_key_base64=signing_key_base64,
        issuer_url=f"https://hypershift-{iam_values.infra_id}-oidc",
        infra_id=iam_values.infra_id,
        project_id=iam_values.project_id,
        region=getattr(infra_values, "region", None),
        network=getattr(infra_values, "network", None),
        subnet=getattr(infra_values, "subnet", None),
    )


def _build_cluster_spec(
    cluster_name: str,
    cluster_config: ClusterConfig,
    description: Optional[str] = None,
    endpoint_access: str = "Private",
) -> Dict:
    """Build the cluster data payload for API submission.

    Args:
        cluster_name: Name for the cluster
        cluster_config: Complete cluster configuration
        description: Optional cluster description
        endpoint_access: API server endpoint access mode (Private or PublicAndPrivate)

    Returns:
        Complete cluster data dict ready for API submission
    """
    gcp_spec: Dict = {
        "projectID": cluster_config.project_id,
        "region": cluster_config.region,
        "network": cluster_config.network,
        "subnet": cluster_config.subnet,
        "endpointAccess": endpoint_access,
        "workloadIdentity": cluster_config.wif_spec,
    }

    cluster_data = {
        "name": cluster_name,
        "target_project_id": cluster_config.project_id,
        "spec": {
            "infraID": cluster_config.infra_id,
            "issuerURL": cluster_config.issuer_url,
            "serviceAccountSigningKey": cluster_config.signing_key_base64,
            "platform": {
                "type": "GCP",
                "gcp": gcp_spec,
            },
        },
    }

    if description:
        cluster_data["description"] = description

    return cluster_data


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
# CLI Commands
# =============================================================================


@click.group("clusters")
def clusters_group() -> None:
    """Manage clusters."""
    pass


@clusters_group.command("login")
@click.argument("cluster_name")
@click.option(
    "--server",
    help="API server URL (required if CLS Backend not configured)",
)
@click.option(
    "--kubeconfig",
    type=click.Path(),
    envvar="KUBECONFIG",
    help="Path to kubeconfig file (default: $KUBECONFIG or ~/.kube/config)",
)
@click.option(
    "--namespace",
    default="default",
    help="Default namespace for the context",
)
@click.option(
    "--insecure-skip-tls-verify/--no-insecure-skip-tls-verify",
    default=True,
    help="Skip TLS certificate verification (default: skip)",
)
@click.pass_obj
def login(
    cli_context: "CLIContext",
    cluster_name: str,
    server: str,
    kubeconfig: str,
    namespace: str,
    insecure_skip_tls_verify: bool,
) -> None:
    """Login to a hosted cluster using Google credentials.

    CLUSTER_NAME: Name of the cluster to login to.

    This command authenticates you to a hosted cluster using your Google
    identity. It will:

    1. Get your Google ID token (from gcloud)
    2. Validate it against the cluster API server
    3. Update your kubeconfig with the credentials

    If 'oc' CLI is available, it will be used for the login. Otherwise,
    the kubeconfig will be updated directly.

    Examples:

      # Login using CLS Backend (if configured)
      gcphcp clusters login my-cluster

      # Login with explicit server URL
      gcphcp clusters login my-cluster --server https://api.example.com:443

      # Login to a specific kubeconfig file
      gcphcp clusters login my-cluster --server https://api.example.com:443 \\
        --kubeconfig ~/.kube/my-cluster-config
    """
    try:
        # Step 1: Resolve API endpoint
        endpoint = _resolve_cluster_endpoint(cli_context, cluster_name, server)

        # Step 2: Get Google credentials
        token = _get_google_credentials(cli_context)

        # Step 3: Validate credentials against cluster
        user_info = _validate_credentials(
            cli_context, endpoint, token, insecure_skip_tls_verify
        )

        # Step 4: Perform login
        context_name = _perform_login(
            cli_context=cli_context,
            cluster_name=cluster_name,
            endpoint=endpoint,
            token=token,
            kubeconfig=kubeconfig,
            namespace=namespace,
            insecure_skip_tls_verify=insecure_skip_tls_verify,
        )

        # Step 5: Print success
        _print_login_success(
            cli_context, cluster_name, endpoint, user_info, context_name
        )

    except click.ClickException:
        raise
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        raise click.ClickException(str(e))


def _get_google_credentials(cli_context: "CLIContext") -> str:
    """Step 2: Get Google ID token.

    Returns:
        Google ID token string

    Raises:
        click.ClickException: If token cannot be obtained
    """
    from ...utils.kubeconfig import KubeconfigError, get_google_id_token

    if not cli_context.quiet:
        cli_context.console.print("Getting Google credentials...")

    try:
        return get_google_id_token()
    except KubeconfigError as e:
        raise click.ClickException(str(e))


def _validate_credentials(
    cli_context: "CLIContext",
    endpoint: str,
    token: str,
    insecure_skip_tls_verify: bool,
) -> dict:
    """Step 3: Validate token against cluster API server.

    Returns:
        User info dictionary with email and domain

    Raises:
        click.ClickException: If validation fails
    """
    from ...utils.kubeconfig import KubeconfigError, validate_token

    if not cli_context.quiet:
        cli_context.console.print(f"Authenticating to {endpoint}...")

    try:
        return validate_token(endpoint, token, insecure_skip_tls_verify)
    except KubeconfigError as e:
        raise click.ClickException(str(e))


def _perform_login(
    cli_context: "CLIContext",
    cluster_name: str,
    endpoint: str,
    token: str,
    kubeconfig: str,
    namespace: str,
    insecure_skip_tls_verify: bool,
) -> str:
    """Step 4: Perform login - use oc if available, otherwise direct kubeconfig.

    Returns:
        Context name that was set

    Raises:
        click.ClickException: If login fails
    """
    from ...utils.kubeconfig import (
        KubeconfigError,
        check_oc_installed,
        login_with_oc,
        update_kubeconfig,
    )

    if check_oc_installed(cli_context.config):
        if not cli_context.quiet:
            cli_context.console.print("[dim]Using oc CLI for login...[/dim]")
        try:
            login_with_oc(
                server=endpoint,
                token=token,
                kubeconfig_path=kubeconfig,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
                config=cli_context.config,
            )
            return cluster_name  # oc sets its own context name
        except KubeconfigError as e:
            raise click.ClickException(str(e))
    else:
        if not cli_context.quiet:
            cli_context.console.print(
                "[dim]oc not found, updating kubeconfig directly...[/dim]"
            )
        try:
            return update_kubeconfig(
                cluster_name=cluster_name,
                server=endpoint,
                token=token,
                namespace=namespace,
                kubeconfig_path=kubeconfig,
                insecure_skip_tls_verify=insecure_skip_tls_verify,
            )
        except KubeconfigError as e:
            raise click.ClickException(str(e))


def _print_login_success(
    cli_context: "CLIContext",
    cluster_name: str,
    endpoint: str,
    user_info: dict,
    context_name: str,
) -> None:
    """Step 5: Print success message."""
    if cli_context.quiet:
        return

    cli_context.console.print()
    cli_context.console.print(
        f"[green]✓[/green] Logged into [cyan]{cluster_name}[/cyan]"
    )
    cli_context.console.print(f"  Server: {endpoint}")
    cli_context.console.print(f"  User: {user_info.get('email', 'unknown')}")
    if user_info.get("hd"):
        cli_context.console.print(f"  Domain: {user_info['hd']}")
    cli_context.console.print(f"  Context: {context_name}")
    cli_context.console.print()
    cli_context.console.print("[dim]You can now use kubectl/oc commands.[/dim]")


def _resolve_cluster_endpoint(
    cli_context: "CLIContext",
    cluster_name: str,
    server: str,
) -> str:
    """Resolve the API server endpoint for a cluster.

    Priority:
    1. Explicit --server flag
    2. CLS Backend API (if configured)
    3. Error with usage message

    Args:
        cli_context: CLI context
        cluster_name: Name of the cluster
        server: Explicit server URL (may be None)

    Returns:
        API server endpoint URL

    Raises:
        click.ClickException: If endpoint cannot be resolved
    """
    # Option 1: Explicit server flag
    if server:
        return server

    # Option 2: Try CLS Backend API (if configured)
    api_url = cli_context.config.get("api_endpoint")
    if api_url:
        try:
            api_client = cli_context.get_api_client()
            cluster_id = resolve_cluster_identifier(api_client, cluster_name)

            # Get cluster status to find the API endpoint
            status_data = api_client.get(f"/api/v1/clusters/{cluster_id}/status")

            # Look for APIServer condition in controller status
            controller_statuses = status_data.get("controller_status", [])
            for controller in controller_statuses:
                conditions = controller.get("conditions", [])
                for condition in conditions:
                    if condition.get("type") == "APIServer":
                        message = condition.get("message", "")
                        # The message contains the API endpoint URL
                        if message.startswith("https://"):
                            if not cli_context.quiet:
                                cli_context.console.print(
                                    "[dim]Resolved endpoint from CLS Backend[/dim]"
                                )
                            return message

            # Fallback: check if there's an api_endpoint field in cluster data
            cluster = api_client.get(f"/api/v1/clusters/{cluster_id}")
            if cluster.get("api_endpoint"):
                return cluster["api_endpoint"]

        except (APIError, ResourceNotFoundError) as e:
            # Fall through to error with more context
            raise click.ClickException(
                f"Failed to resolve endpoint for cluster '{cluster_name}' "
                f"from CLS Backend: {e}\n\n"
                "Please specify the server URL manually:\n"
                f"  gcphcp clusters login {cluster_name} --server <API_URL>"
            )
        except Exception:
            # Fall through to error
            pass

    # Option 3: Error with usage
    raise click.ClickException(
        f"Cannot determine API endpoint for cluster '{cluster_name}'.\n\n"
        "Please specify the server URL:\n"
        f"  gcphcp clusters login {cluster_name} --server <API_URL>\n\n"
        "Or configure the CLS Backend API:\n"
        "  gcphcp config set api_endpoint <CLS_BACKEND_URL>"
    )


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

            # Fetch nodepools for this cluster
            nodepools: List[Dict[str, Any]] = []
            try:
                nodepools_response = api_client.get(
                    "/api/v1/nodepools", params={"clusterId": cluster_id}
                )
                nodepools = nodepools_response.get("nodepools") or []
            except APIError:
                # Don't fail if nodepools fetch fails - just show empty list
                pass

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
                cli_context.formatter.print_cluster_status(
                    cluster, cluster_id, nodepools=nodepools
                )

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
    help="Automatically provision infrastructure (keypair + IAM + network)",
)
@click.option(
    "--vpc-cidr",
    default="10.0.0.0/24",
    help="CIDR block for subnet (with --setup-infra, default: 10.0.0.0/24)",
)
@click.option(
    "--iam-config-file",
    type=click.Path(exists=True),
    help="Path to IAM/WIF config JSON from 'gcphcp infra create'",
)
@click.option(
    "--signing-key-file",
    type=click.Path(exists=True),
    help="Path to PEM-encoded RSA private key for SA signing",
)
@click.option(
    "--infra-config-file",
    type=click.Path(exists=True),
    help="Path to infra config JSON from 'hypershift create infra'",
)
@click.option(
    "--network",
    help="VPC network name (required if --infra-config-file not provided)",
)
@click.option(
    "--subnet",
    help="Subnet name (required if --infra-config-file not provided)",
)
@click.option(
    "--endpoint-access",
    type=click.Choice(["Private", "PublicAndPrivate"], case_sensitive=True),
    default="PublicAndPrivate",
    help="API server endpoint access mode (default: PublicAndPrivate)",
)
@click.option(
    "--replicas",
    type=int,
    help=(
        "Number of compute nodes for default nodepool "
        "(if not specified, no nodepool created)"
    ),
)
@click.option(
    "--node-machine-type",
    default="n1-standard-4",
    help="Machine type for default nodepool (default: n1-standard-4)",
)
@click.option(
    "--node-disk-size",
    type=int,
    default=128,
    help="Boot disk size in GB for default nodepool (default: 128)",
)
@click.option(
    "--node-disk-type",
    type=click.Choice(["pd-standard", "pd-ssd", "pd-balanced"], case_sensitive=False),
    default="pd-standard",
    help="Boot disk type for default nodepool (default: pd-standard)",
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
    vpc_cidr: str,
    iam_config_file: str,
    signing_key_file: str,
    infra_config_file: str,
    network: str,
    subnet: str,
    endpoint_access: str,
    replicas: Optional[int],
    node_machine_type: str,
    node_disk_size: int,
    node_disk_type: str,
    dry_run: bool,
) -> None:
    """Create a new cluster.

    CLUSTER_NAME: Name for the new cluster (must be DNS-compatible).

    NOTE: Infrastructure ID (defaults to cluster name) must be 15 characters
    or less. Use --infra-id to specify a shorter identifier if needed.

    \b
    Two modes of operation:

    \b
    1. Automatic Infrastructure Provisioning Mode:
       CLI automatically generates keypair and provisions required
       infrastructure (IAM, Network). Use --setup-infra flag.

    \b
    2. Pre-Provisioned Infrastructure Mode:
       Pre-create infrastructure using 'gcphcp infra create', then use
       the generated config files (--iam-config-file, --signing-key-file,
       --infra-config-file) for cluster creation.

    \b
    Examples:

    \b
    Automatic Infrastructure Provisioning Mode:
      gcphcp clusters create my-cluster --project my-project --setup-infra

    \b
    Pre-Provisioned Infrastructure Mode:
      gcphcp clusters create my-cluster \\
          --iam-config-file infra-iam-config.json \\
          --signing-key-file infra-signing-key.pem \\
          --infra-config-file infra-config.json

    \b
    Config files with explicit network:
      gcphcp clusters create my-cluster \\
          --iam-config-file infra-iam-config.json \\
          --signing-key-file infra-signing-key.pem \\
          --network my-vpc --subnet my-subnet

    \b
    Dry run to preview cluster spec:
      gcphcp clusters create my-cluster --setup-infra --project my-proj --dry-run
    """
    try:
        # =================================================================
        # Resolve common input values
        # =================================================================
        target_project = project or cli_context.config.get("default_project")
        effective_infra_id = infra_id or cluster_name
        effective_region = region

        # =================================================================
        # Validate infra-id length for GCP resource constraints
        # =================================================================
        from ...utils.hypershift import validate_infra_id_length

        try:
            validate_infra_id_length(effective_infra_id)
        except ValueError as e:
            raise click.ClickException(
                f"{e}\nUse --infra-id to specify a shorter identifier."
            )

        # =================================================================
        # Mode Selection: Infrastructure Provisioning vs Config Files
        # =================================================================

        if setup_infra:
            # =============================================================
            # INFRASTRUCTURE PROVISIONING: Create IAM + network, use returned values
            # =============================================================

            # Project is required for --setup-infra
            if not target_project:
                cli_context.console.print(
                    "[red]Project ID required. Use --project or default_project.[/red]"
                )
                raise click.ClickException("Project ID required")

            # Warn if config files provided in setup-infra mode
            if iam_config_file or infra_config_file:
                if not cli_context.quiet:
                    cli_context.console.print(
                        "[yellow]Note: Config files are ignored "
                        "when --setup-infra is used[/yellow]"
                    )

            # Create infrastructure
            infra_result = _setup_cluster_infra(
                cli_context=cli_context,
                infra_id=effective_infra_id,
                project_id=target_project,
                region=effective_region,
                vpc_cidr=vpc_cidr,
            )

            # Use values from created infrastructure as source of truth
            resolved_infra_id = infra_result.infra_id
            target_project = infra_result.project_id
            effective_network = infra_result.network
            effective_subnet = infra_result.subnet
            effective_region = infra_result.region or effective_region

        else:
            # =============================================================
            # CONFIG FILES: Load pre-generated config files
            # =============================================================

            if not iam_config_file:
                cli_context.console.print(
                    "[red]Error: --iam-config-file is required[/red]"
                )
                raise click.ClickException(
                    "Either use --setup-infra to provision infrastructure, "
                    "or provide --iam-config-file with pre-generated config"
                )

            if not signing_key_file:
                cli_context.console.print(
                    "[red]Error: --signing-key-file is required "
                    "with --iam-config-file[/red]"
                )
                raise click.ClickException(
                    "--signing-key-file is required with --iam-config-file"
                )

            # Load and validate all config files in one place
            infra_result = _load_cluster_config(
                cli_context=cli_context,
                iam_config_file=iam_config_file,
                signing_key_file=signing_key_file,
                infra_config_file=infra_config_file,
            )

            # Use config file values, fall back to CLI flags
            resolved_infra_id = infra_result.infra_id
            effective_network = infra_result.network or network
            effective_subnet = infra_result.subnet or subnet
            effective_region = infra_result.region or effective_region

            # Handle project_id override from config files
            if infra_result.project_id:
                if target_project and target_project != infra_result.project_id:
                    if not cli_context.quiet:
                        cli_context.console.print(
                            f"[yellow]Using projectId '{infra_result.project_id}' "
                            f"from config (overrides '{target_project}')[/yellow]"
                        )
                target_project = infra_result.project_id

            # Validate project ID is set
            if not target_project:
                cli_context.console.print(
                    "[red]Project ID required. Use --project, set default_project, "
                    "or provide config files with projectId.[/red]"
                )
                raise click.ClickException("Project ID required")

            # Validate network and subnet
            if not effective_network or not effective_subnet:
                missing = []
                if not effective_network:
                    missing.append("network")
                if not effective_subnet:
                    missing.append("subnet")
                raise click.ClickException(
                    f"Missing network configuration: {', '.join(missing)}. "
                    "Use --network/--subnet flags or --infra-config-file."
                )

        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print("[bold cyan]Creating Cluster[/bold cyan]")

        # =================================================================
        # Build final setup config with resolved values
        # =================================================================
        from dataclasses import replace

        cluster_config = replace(
            infra_result,
            project_id=target_project,
            region=effective_region,
            infra_id=resolved_infra_id,
            network=effective_network,
            subnet=effective_subnet,
        )

        # =================================================================
        # Build Cluster Spec and Submit to API
        # =================================================================

        cluster_data = _build_cluster_spec(
            cluster_name=cluster_name,
            cluster_config=cluster_config,
            description=description,
            endpoint_access=endpoint_access,
        )

        if dry_run:
            cli_context.console.print("[yellow]Dry run - would create:[/yellow]")
            # Truncate signing key for display (it's very long)
            import copy

            display_data = copy.deepcopy(cluster_data)
            spec = display_data.get("spec", {})
            signing_key = spec.get("serviceAccountSigningKey", "")
            if signing_key and len(signing_key) > 20:
                spec["serviceAccountSigningKey"] = signing_key[:20] + "..."
            # Always use JSON for dry-run output (cluster spec is deeply nested)
            dry_run_json = json.dumps(display_data, indent=2, ensure_ascii=False)
            cli_context.console.print(dry_run_json)
            return

        if not cli_context.quiet:
            cli_context.console.print(
                f"Creating cluster '{cluster_name}' in project '{target_project}'..."
            )
            if cli_context.verbosity >= 2:
                cli_context.console.print("[dim]Debug - Sending cluster_data:[/dim]")
                # Use direct file write to avoid Rich formatting issues with JSON
                debug_json = json.dumps(cluster_data, indent=2, ensure_ascii=False)
                cli_context.console.file.write(f"{debug_json}\n")
                cli_context.console.file.flush()

        api_client = cli_context.get_api_client()

        cluster = api_client.post("/api/v1/clusters", json_data=cluster_data)
        cluster_id = cluster.get("id")

        # Create default nodepool if --replicas specified
        if replicas:
            try:
                if not cli_context.quiet:
                    cli_context.console.print()
                    cli_context.console.print(
                        "[bold cyan]Creating Default NodePool[/bold cyan]"
                    )

                # Generate nodepool name
                nodepool_name = f"{cluster_name}-nodepool-1"

                # Build nodepool spec
                nodepool_data = {
                    "name": nodepool_name,
                    "cluster_id": cluster_id,
                    "spec": {
                        "replicas": replicas,
                        "platform": {
                            "type": "GCP",
                            "gcp": {
                                "instanceType": node_machine_type,
                                "rootVolume": {
                                    "size": node_disk_size,
                                    "type": node_disk_type,
                                },
                            },
                        },
                        "management": {"autoRepair": True, "upgradeType": "Replace"},
                    },
                }

                _ = api_client.post("/api/v1/nodepools", json_data=nodepool_data)

                if not cli_context.quiet:
                    cli_context.console.print(
                        f"[green]✓[/green] NodePool '{nodepool_name}' "
                        f"created with {replicas} replica(s)"
                    )

            except APIError as e:
                # Don't fail cluster creation if nodepool creation fails
                if not cli_context.quiet:
                    cli_context.console.print(
                        f"[yellow]Warning: Cluster created but "
                        f"nodepool creation failed: {e}[/yellow]"
                    )
                    cli_context.console.print(
                        f"[dim]Create manually with:[/dim]\n"
                        f"  gcphcp nodepools create {nodepool_name} "
                        f"--cluster {cluster_id} --replicas {replicas}"
                    )

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
