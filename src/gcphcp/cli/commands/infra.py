"""Infrastructure management commands for GCP HCP CLI."""

import click
from typing import TYPE_CHECKING

from ...constants import DEFAULT_REGION

if TYPE_CHECKING:
    from ..main import CLIContext


@click.group("infra")
def infra_group() -> None:
    """Manage infrastructure for hosted cluster deployments."""
    pass


@infra_group.command("create")
@click.argument("infra_id")
@click.option(
    "--project",
    help="Target project ID (overrides default)",
)
@click.option(
    "--region",
    default=DEFAULT_REGION,
    help=f"GCP region for network resources (default: {DEFAULT_REGION})",
)
@click.option(
    "--vpc-cidr",
    default="10.0.0.0/24",
    help="CIDR block for the subnet (default: 10.0.0.0/24)",
)
@click.option(
    "--oidc-jwks-file",
    type=click.Path(exists=True),
    help="Path to OIDC JWKS file (if not provided, a keypair will be generated)",
)
@click.option(
    "--output-signing-key",
    type=click.Path(),
    help="Path for signing key PEM (default: <infra-id>-signing-key.pem)",
)
@click.option(
    "--output-jwks",
    type=click.Path(),
    help="Path to save the generated JWKS file (default: <infra-id>-jwks.json)",
)
@click.option(
    "--output-iam-config",
    type=click.Path(),
    help="Path for IAM config JSON (default: <infra-id>-iam-config.json)",
)
@click.option(
    "--output-infra-config",
    type=click.Path(),
    help="Path for network infra config JSON (default: <infra-id>-infra-config.json)",
)
@click.pass_obj
def create_infra(
    cli_context: "CLIContext",
    infra_id: str,
    project: str,
    region: str,
    vpc_cidr: str,
    oidc_jwks_file: str,
    output_signing_key: str,
    output_jwks: str,
    output_iam_config: str,
    output_infra_config: str,
) -> None:
    """Create infrastructure for hosted cluster deployment.

    INFRA_ID: Infrastructure identifier (must be DNS-compatible, max 15 chars).

    This command provisions the necessary infrastructure components including:
    - RSA keypair for service account signing (if JWKS not provided)
    - Workload Identity Federation (WIF) infrastructure
    - Network infrastructure (VPC, subnet, router, NAT)

    All generated files are automatically saved to the current directory with
    default filenames based on the infra-id. You can override the paths using
    the --output-* options.

    Default output files:
    - <infra-id>-signing-key.pem: RSA private key for service account signing
    - <infra-id>-jwks.json: JWKS file with public key
    - <infra-id>-iam-config.json: Complete IAM/WIF configuration from hypershift
    - <infra-id>-infra-config.json: Network infrastructure configuration

    Examples:

      # Create infrastructure (saves to default filenames)
      gcphcp infra create my-infra --project my-project --region us-central1

      # Create infrastructure with custom VPC CIDR
      gcphcp infra create my-infra --project my-project --vpc-cidr 10.1.0.0/24

      # Create infrastructure with custom output paths
      gcphcp infra create my-infra --project my-project \\
        --output-signing-key ./keys/signing-key.pem \\
        --output-jwks ./keys/jwks.json \\
        --output-iam-config ./config/iam.json \\
        --output-infra-config ./config/infra.json

      # Create infrastructure with existing JWKS
      gcphcp infra create my-infra --project my-project \\
        --oidc-jwks-file ./existing-jwks.json
    """
    try:
        from ...utils.hypershift import (
            create_iam_gcp,
            create_infra_gcp,
            validate_iam_config,
            validate_infra_config,
            HypershiftError,
        )
        from ...utils.crypto import generate_cluster_keypair
        import json
        import shutil

        # Use project from command line or config
        target_project = project or cli_context.config.get("default_project")
        if not target_project:
            cli_context.console.print(
                "[red]Project ID required. Use --project or set default_project.[/red]"
            )
            raise click.ClickException("Project ID required")

        # =================================================================
        # Validate infra-id length for GCP resource constraints
        # =================================================================
        from ...utils.hypershift import validate_infra_id_length

        try:
            validate_infra_id_length(infra_id)
        except ValueError as e:
            raise click.ClickException(str(e))

        keypair_result = None
        jwks_file_to_use = oidc_jwks_file

        # Step 1: Generate keypair if JWKS file not provided
        if not oidc_jwks_file:
            if not cli_context.quiet:
                cli_context.console.print()
                cli_context.console.print(
                    "[bold cyan]Step 1: Generate Keypair[/bold cyan]"
                )

            try:
                keypair_result = generate_cluster_keypair()
                jwks_file_to_use = keypair_result.jwks_file_path

                if not cli_context.quiet:
                    cli_context.console.print(
                        "[green]✓[/green] Keypair generated successfully"
                    )
                    cli_context.console.print(f"[dim]  kid: {keypair_result.kid}[/dim]")

                # Save signing key (use default filename if not specified)
                signing_key_path = output_signing_key or f"{infra_id}-signing-key.pem"
                with open(signing_key_path, "w") as f:
                    f.write(keypair_result.private_key_pem)
                if not cli_context.quiet:
                    cli_context.console.print(
                        f"[green]✓[/green] Signing key saved to: {signing_key_path}"
                    )

                # Save JWKS (use default filename if not specified)
                jwks_path = output_jwks or f"{infra_id}-jwks.json"
                shutil.copy(keypair_result.jwks_file_path, jwks_path)
                if not cli_context.quiet:
                    cli_context.console.print(
                        f"[green]✓[/green] JWKS saved to: {jwks_path}"
                    )

            except Exception as e:
                raise click.ClickException(f"Failed to generate keypair: {e}")

        # Step 2: Setup IAM Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 2: Setup IAM Infrastructure[/bold cyan]"
            )

        try:
            # Run hypershift create iam gcp
            iam_config = create_iam_gcp(
                infra_id=infra_id,
                project_id=target_project,
                oidc_jwks_file=jwks_file_to_use,
                console=cli_context.console if not cli_context.quiet else None,
                config=cli_context.config,
            )

            # Validate the output
            if not validate_iam_config(iam_config):
                raise click.ClickException(
                    "Invalid IAM configuration returned from hypershift"
                )

            # Save IAM config (use default filename if not specified)
            iam_config_path = output_iam_config or f"{infra_id}-iam-config.json"
            with open(iam_config_path, "w") as f:
                json.dump(iam_config, f, indent=2)
            if not cli_context.quiet:
                cli_context.console.print(
                    f"[green]✓[/green] IAM configuration saved to: {iam_config_path}"
                )

        except HypershiftError as e:
            cli_context.console.print(f"[red]Failed to setup IAM: {e}[/red]")
            raise click.ClickException(str(e))

        # Step 3: Setup Network Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 3: Setup Network Infrastructure[/bold cyan]"
            )

        try:
            # Run hypershift create infra gcp
            infra_config = create_infra_gcp(
                infra_id=infra_id,
                project_id=target_project,
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

            # Save infra config (use default filename if not specified)
            infra_config_path = output_infra_config or f"{infra_id}-infra-config.json"
            with open(infra_config_path, "w") as f:
                json.dump(infra_config, f, indent=2)
            if not cli_context.quiet:
                cli_context.console.print(
                    f"[green]✓[/green] Infra config saved to: {infra_config_path}"
                )

        except HypershiftError as e:
            cli_context.console.print(f"[red]Failed to setup network: {e}[/red]")
            raise click.ClickException(str(e))

        # Print summary
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[green]✓ All infrastructure created successfully![/green]"
            )
            cli_context.console.print()
            cli_context.console.print("[bold]IAM Configuration:[/bold]")
            cli_context.console.print_json(data=iam_config)
            cli_context.console.print()
            cli_context.console.print("[bold]Network Configuration:[/bold]")
            cli_context.console.print_json(data=infra_config)

            cli_context.console.print()
            cli_context.console.print("[bold]Saved Files:[/bold]")
            if keypair_result:
                signing_key_path = output_signing_key or f"{infra_id}-signing-key.pem"
                jwks_path = output_jwks or f"{infra_id}-jwks.json"
                cli_context.console.print(f"  • Signing key: {signing_key_path}")
                cli_context.console.print(f"  • JWKS: {jwks_path}")
            cli_context.console.print(f"  • IAM config: {iam_config_path}")
            cli_context.console.print(f"  • Infra config: {infra_config_path}")
        else:
            # Output combined config in quiet mode
            combined_config = {
                "iam": iam_config,
                "infra": infra_config,
            }
            cli_context.formatter.print_data(combined_config)

        # Clean up temporary JWKS file
        if keypair_result:
            keypair_result.cleanup()

    except click.ClickException:
        raise
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        import sys

        sys.exit(1)


@infra_group.command("destroy")
@click.argument("infra_id")
@click.option(
    "--project",
    help="Target project ID (overrides default)",
)
@click.option(
    "--region",
    default=DEFAULT_REGION,
    help=f"GCP region where network resources are located (default: {DEFAULT_REGION})",
)
@click.option(
    "--yes",
    "-y",
    is_flag=True,
    help="Skip confirmation prompt",
)
@click.pass_obj
def destroy_infra(
    cli_context: "CLIContext",
    infra_id: str,
    project: str,
    region: str,
    yes: bool,
) -> None:
    """Destroy infrastructure created for hosted cluster deployment.

    INFRA_ID: Infrastructure identifier used when creating the infrastructure.

    This command removes infrastructure components including:
    - Workload Identity Federation (WIF) pool and provider
    - Service accounts for control plane and node pool management
    - Network infrastructure (VPC, subnet, router, NAT)

    WARNING: This action is irreversible. All resources with the specified
    infra-id will be permanently deleted.

    Examples:

      # Destroy infrastructure (with confirmation prompt)
      gcphcp infra destroy my-infra --project my-project --region us-central1

      # Destroy infrastructure without confirmation
      gcphcp infra destroy my-infra --project my-project --region us-central1 --yes
    """
    try:
        from ...utils.hypershift import (
            destroy_iam_gcp,
            destroy_infra_gcp,
            HypershiftError,
        )

        # Use project from command line or config
        target_project = project or cli_context.config.get("default_project")
        if not target_project:
            cli_context.console.print(
                "[red]Project ID required. Use --project or set default_project.[/red]"
            )
            raise click.ClickException("Project ID required")

        # Confirmation prompt unless --yes is specified
        if not yes:
            cli_context.console.print()
            cli_context.console.print(
                "[bold yellow]⚠ WARNING: You are about to destroy "
                "infrastructure![/bold yellow]"
            )
            cli_context.console.print()
            cli_context.console.print(f"  Infrastructure ID: [cyan]{infra_id}[/cyan]")
            cli_context.console.print(f"  Project ID: [cyan]{target_project}[/cyan]")
            cli_context.console.print(f"  Region: [cyan]{region}[/cyan]")
            cli_context.console.print()
            cli_context.console.print("This will permanently delete:")
            cli_context.console.print("  • Workload Identity Pool and Provider")
            cli_context.console.print(
                "  • Service Accounts (control plane and node pool)"
            )
            cli_context.console.print("  • VPC Network, Subnet, Router, and NAT")
            cli_context.console.print()

            if not click.confirm("Do you want to continue?"):
                cli_context.console.print("[yellow]Aborted.[/yellow]")
                return

        # Step 1: Destroy Network Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 1: Destroy Network Infrastructure[/bold cyan]"
            )

        network_destroyed = False
        try:
            destroy_infra_gcp(
                infra_id=infra_id,
                project_id=target_project,
                region=region,
                console=cli_context.console if not cli_context.quiet else None,
                config=cli_context.config,
            )
            network_destroyed = True
            if not cli_context.quiet:
                cli_context.console.print(
                    "[green]✓[/green] Network infrastructure destroyed"
                )
        except HypershiftError as e:
            cli_context.console.print(
                f"[yellow]Warning: Failed to destroy network "
                f"infrastructure: {e}[/yellow]"
            )
            cli_context.console.print(
                "[yellow]Continuing with IAM destruction...[/yellow]"
            )

        # Step 2: Destroy IAM Infrastructure
        iam_destroyed = False
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print(
                "[bold cyan]Step 2: Destroy IAM Infrastructure[/bold cyan]"
            )

        try:
            destroy_iam_gcp(
                infra_id=infra_id,
                project_id=target_project,
                console=cli_context.console if not cli_context.quiet else None,
                config=cli_context.config,
            )
            iam_destroyed = True
            if not cli_context.quiet:
                cli_context.console.print(
                    "[green]✓[/green] IAM infrastructure destroyed"
                )
        except HypershiftError as e:
            cli_context.console.print(f"[yellow]Warning: {e}[/yellow]")

        # Print summary
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print("[bold]Summary:[/bold]")
            cli_context.console.print(f"  Infrastructure ID: {infra_id}")
            cli_context.console.print(f"  Project: {target_project}")
            cli_context.console.print(f"  Region: {region}")
            network_status = (
                "[green]destroyed[/green]"
                if network_destroyed
                else "[yellow]failed[/yellow]"
            )
            cli_context.console.print(f"  Network: {network_status}")
            iam_status = (
                "[green]destroyed[/green]"
                if iam_destroyed
                else "[yellow]skipped[/yellow]"
            )
            cli_context.console.print(f"  IAM: {iam_status}")

    except click.ClickException:
        raise
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        import sys

        sys.exit(1)
