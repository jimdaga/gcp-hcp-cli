"""Main CLI entry point for GCP HCP CLI."""

import logging
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.logging import RichHandler

from ..auth.google_auth import GoogleCloudAuth
from ..client.api_client import APIClient
from ..utils.config import Config
from ..utils.formatters import OutputFormatter
from .commands import auth, clusters, config as config_cmd

# Global console for rich output
console = Console()

# Default configuration
DEFAULT_API_ENDPOINT = "https://api.gcphcp.example.com"
DEFAULT_CONFIG_PATH = Path.home() / ".gcphcp" / "config.yaml"


def setup_logging(verbosity: int) -> None:
    """Set up logging configuration.

    Args:
        verbosity: Logging verbosity level (0-3)
    """
    log_levels = {
        0: logging.WARNING,
        1: logging.INFO,
        2: logging.DEBUG,
        3: logging.DEBUG,
    }

    level = log_levels.get(verbosity, logging.DEBUG)

    # Configure rich logging
    logging.basicConfig(
        level=level,
        format="%(name)s: %(message)s",
        handlers=[RichHandler(console=console, show_path=False)],
    )

    # Reduce noise from third-party libraries
    if level > logging.DEBUG:
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("google").setLevel(logging.WARNING)


class CLIContext:
    """Shared context for CLI commands."""

    def __init__(
        self,
        config: Config,
        output_format: str = "table",
        verbosity: int = 0,
        quiet: bool = False,
    ) -> None:
        """Initialize CLI context.

        Args:
            config: Configuration object
            output_format: Output format for results
            verbosity: Logging verbosity level
            quiet: Whether to suppress non-essential output
        """
        self.config = config
        self.output_format = output_format
        self.verbosity = verbosity
        self.quiet = quiet
        self.console = console

        # Initialize components
        self.auth = GoogleCloudAuth(
            credentials_path=config.get_credentials_path(),
            client_secrets_path=config.get_client_secrets_path(),
            audience=config.get_audience(),
        )

        self.api_client: Optional[APIClient] = None
        self.formatter = OutputFormatter(format_type=output_format, console=console)

    def get_api_client(self) -> APIClient:
        """Get or create API client instance.

        Returns:
            Configured API client instance
        """
        if not self.api_client:
            self.api_client = APIClient(
                base_url=self.config.get_api_endpoint(),
                auth=self.auth,
                user_agent=f"gcphcp-cli/{self.config.get_version()}",
            )
        return self.api_client

    def cleanup(self) -> None:
        """Clean up resources."""
        if self.api_client:
            self.api_client.close()


def create_cli_context(
    config_path: Optional[Path],
    api_endpoint: Optional[str],
    project: Optional[str],
    output_format: str,
    verbosity: int,
    quiet: bool,
) -> CLIContext:
    """Create CLI context with configuration.

    Args:
        config_path: Path to configuration file
        api_endpoint: API endpoint URL
        project: Default project ID
        output_format: Output format
        verbosity: Logging verbosity level
        quiet: Whether to suppress non-essential output

    Returns:
        Configured CLI context
    """
    # Load configuration
    config = Config(config_path or DEFAULT_CONFIG_PATH)

    # Override configuration with command line options
    if api_endpoint:
        config.set("api_endpoint", api_endpoint)
    if project:
        config.set("default_project", project)

    # Set defaults if not configured
    if not config.get("api_endpoint"):
        config.set("api_endpoint", DEFAULT_API_ENDPOINT)

    return CLIContext(
        config=config,
        output_format=output_format,
        verbosity=verbosity,
        quiet=quiet,
    )


# Global options that apply to all commands
@click.group()
@click.option(
    "--config",
    type=click.Path(exists=False, path_type=Path),
    help="Path to configuration file",
)
@click.option(
    "--api-endpoint",
    help="API endpoint URL",
)
@click.option(
    "--project",
    help="Default project ID",
)
@click.option(
    "--format",
    "output_format",
    default="table",
    type=click.Choice(["table", "json", "yaml", "csv", "value"], case_sensitive=False),
    help="Output format",
)
@click.option(
    "-v",
    "--verbose",
    "verbosity",
    count=True,
    help="Increase verbosity (use -v, -vv, or -vvv)",
)
@click.option(
    "-q",
    "--quiet",
    is_flag=True,
    help="Suppress non-essential output",
)
@click.version_option(version="0.1.0", prog_name="gcphcp")
@click.pass_context
def cli(
    ctx: click.Context,
    config: Optional[Path],
    api_endpoint: Optional[str],
    project: Optional[str],
    output_format: str,
    verbosity: int,
    quiet: bool,
) -> None:
    """GCP HCP CLI - Command-line interface for Google Cloud Platform HCP.

    Manage clusters and nodepools through the GCP HCP API with gcloud-style commands
    and output formatting.
    """
    # Set up logging
    setup_logging(verbosity)

    # Create and store CLI context
    cli_context = create_cli_context(
        config_path=config,
        api_endpoint=api_endpoint,
        project=project,
        output_format=output_format,
        verbosity=verbosity,
        quiet=quiet,
    )

    ctx.obj = cli_context

    # Register cleanup function
    ctx.call_on_close(cli_context.cleanup)


# Add command groups
cli.add_command(auth.auth_group)
cli.add_command(clusters.clusters_group)
cli.add_command(config_cmd.config_group)


def main() -> None:
    """Main entry point for the CLI."""
    try:
        cli()
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        if "--verbose" in sys.argv or "-v" in sys.argv:
            console.print_exception()
        else:
            console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
