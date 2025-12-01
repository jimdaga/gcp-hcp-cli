"""Infrastructure management commands for GCP HCP CLI."""

import click
from typing import TYPE_CHECKING

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
    "--oidc-jwks-file",
    type=click.Path(exists=True),
    help="Path to OIDC JWKS file (if not provided, a keypair will be generated)",
)
@click.option(
    "--output-signing-key",
    type=click.Path(),
    help="Path to save the generated signing key PEM file (default: <infra-id>-signing-key.pem)",
)
@click.option(
    "--output-jwks",
    type=click.Path(),
    help="Path to save the generated JWKS file (default: <infra-id>-jwks.json)",
)
@click.option(
    "--output-iam-config",
    type=click.Path(),
    help="Path to save the IAM/WIF configuration JSON (default: <infra-id>-iam-config.json)",
)
@click.pass_obj
def create_infra(
    cli_context: "CLIContext",
    infra_id: str,
    project: str,
    oidc_jwks_file: str,
    output_signing_key: str,
    output_jwks: str,
    output_iam_config: str,
) -> None:
    """Create infrastructure for hosted cluster deployment.

    INFRA_ID: Infrastructure identifier (must be DNS-compatible).

    This command provisions the necessary infrastructure components including:
    - RSA keypair for service account signing (if JWKS not provided)
    - Workload Identity Federation (WIF) infrastructure
    - (Future: Network infrastructure, VPCs, subnets, etc.)

    All generated files are automatically saved to the current directory with
    default filenames based on the infra-id. You can override the paths using
    the --output-* options.

    Default output files:
    - <infra-id>-signing-key.pem: RSA private key for service account signing
    - <infra-id>-jwks.json: JWKS file with public key
    - <infra-id>-iam-config.json: Complete IAM/WIF configuration from hypershift

    Examples:

      # Create infrastructure (saves to default filenames)
      gcphcp infra create my-infra --project my-project
      # Creates: my-infra-signing-key.pem, my-infra-jwks.json, my-infra-iam-config.json

      # Create infrastructure with custom output paths
      gcphcp infra create my-infra --project my-project \\
        --output-signing-key ./keys/signing-key.pem \\
        --output-jwks ./keys/jwks.json \\
        --output-iam-config ./config/iam.json

      # Create infrastructure with existing JWKS
      gcphcp infra create my-infra --project my-project \\
        --oidc-jwks-file ./existing-jwks.json
    """
    try:
        from ...utils.hypershift import (
            create_iam_gcp,
            validate_wif_config,
            HypershiftError,
        )
        from ...utils.crypto import generate_cluster_keypair

        # Use project from command line or config
        target_project = project or cli_context.config.get("default_project")
        if not target_project:
            cli_context.console.print(
                "[red]Project ID required. Use --project or set default_project.[/red]"
            )
            raise click.ClickException("Project ID required")

        keypair_result = None
        jwks_file_to_use = oidc_jwks_file

        # Generate keypair if JWKS file not provided
        if not oidc_jwks_file:
            if not cli_context.quiet:
                cli_context.console.print()
                cli_context.console.print("[bold cyan]Step 1: Generate Keypair[/bold cyan]")

            try:
                keypair_result = generate_cluster_keypair()
                jwks_file_to_use = keypair_result.jwks_file_path

                if not cli_context.quiet:
                    cli_context.console.print("[green]✓[/green] Keypair generated successfully")
                    cli_context.console.print(f"[dim]  kid: {keypair_result.kid}[/dim]")

                # Save signing key (use default filename if not specified)
                signing_key_path = output_signing_key or f"{infra_id}-signing-key.pem"
                with open(signing_key_path, 'w') as f:
                    f.write(keypair_result.private_key_pem)
                if not cli_context.quiet:
                    cli_context.console.print(f"[green]✓[/green] Signing key saved to: {signing_key_path}")

                # Save JWKS (use default filename if not specified)
                jwks_path = output_jwks or f"{infra_id}-jwks.json"
                import shutil
                shutil.copy(keypair_result.jwks_file_path, jwks_path)
                if not cli_context.quiet:
                    cli_context.console.print(f"[green]✓[/green] JWKS saved to: {jwks_path}")

            except Exception as e:
                raise click.ClickException(f"Failed to generate keypair: {e}")

        # Setup WIF Infrastructure
        if not cli_context.quiet:
            cli_context.console.print()
            cli_context.console.print("[bold cyan]Step 2: Setup WIF Infrastructure[/bold cyan]")

        try:
            # Run hypershift create iam gcp
            wif_config = create_iam_gcp(
                infra_id=infra_id,
                project_id=target_project,
                oidc_jwks_file=jwks_file_to_use,
                console=cli_context.console if not cli_context.quiet else None,
                config=cli_context.config,
            )

            # Validate the output
            if not validate_wif_config(wif_config):
                raise click.ClickException(
                    "Invalid WIF configuration returned from hypershift"
                )

            # Save WIF config (use default filename if not specified)
            iam_config_path = output_iam_config or f"{infra_id}-iam-config.json"
            import json
            with open(iam_config_path, 'w') as f:
                json.dump(wif_config, f, indent=2)
            if not cli_context.quiet:
                cli_context.console.print(f"[green]✓[/green] IAM configuration saved to: {iam_config_path}")

            if not cli_context.quiet:
                cli_context.console.print()
                cli_context.console.print("[green]✓ WIF infrastructure created successfully![/green]")
                cli_context.console.print()
                cli_context.console.print("[bold]Infrastructure Details:[/bold]")
                # Use JSON format for nested WIF config to show all details
                cli_context.console.print_json(data=wif_config)
                
                cli_context.console.print()
                cli_context.console.print("[bold]Saved Files:[/bold]")
                if keypair_result:
                    signing_key_path = output_signing_key or f"{infra_id}-signing-key.pem"
                    jwks_path = output_jwks or f"{infra_id}-jwks.json"
                    cli_context.console.print(f"  • Signing key: {signing_key_path}")
                    cli_context.console.print(f"  • JWKS: {jwks_path}")
                iam_config_path = output_iam_config or f"{infra_id}-iam-config.json"
                cli_context.console.print(f"  • IAM config: {iam_config_path}")
            else:
                cli_context.formatter.print_data(wif_config)

        except HypershiftError as e:
            cli_context.console.print(f"[red]Failed to setup infrastructure: {e}[/red]")
            raise click.ClickException(str(e))
        finally:
            # Clean up temporary JWKS file (we always save it now)
            if keypair_result:
                keypair_result.cleanup()

    except click.ClickException:
        raise
    except Exception as e:
        cli_context.console.print(f"[red]Unexpected error: {e}[/red]")
        import sys
        sys.exit(1)
