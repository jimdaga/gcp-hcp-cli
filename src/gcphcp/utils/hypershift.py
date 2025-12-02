"""Utilities for interacting with the hypershift CLI."""

import json
import os
import subprocess
import shutil
from typing import Dict, Any, Optional
from rich.console import Console


class HypershiftError(Exception):
    """Exception raised when hypershift CLI operations fail."""

    pass


def get_hypershift_binary(config=None) -> Optional[str]:
    """Get the path to the hypershift binary.

    Checks in order:
    1. HYPERSHIFT_BINARY environment variable
    2. hypershift_binary config setting (if config provided)
    3. 'hypershift' in PATH

    Args:
        config: Optional Config object to check for hypershift_binary setting

    Returns:
        Path to hypershift binary or None if not found
    """
    # Check environment variable first
    env_binary = os.environ.get("HYPERSHIFT_BINARY")
    if env_binary and os.path.isfile(env_binary):
        return env_binary

    # Check config if provided
    if config:
        config_binary = config.get_hypershift_binary()
        if config_binary and os.path.isfile(config_binary):
            return config_binary

    # Check in PATH
    path_binary = shutil.which("hypershift")
    if path_binary:
        return path_binary

    return None


def check_hypershift_installed() -> bool:
    """Check if hypershift CLI is installed and available.

    Returns:
        True if hypershift is installed, False otherwise
    """
    return get_hypershift_binary() is not None


def create_iam_gcp(
    infra_id: str,
    project_id: str,
    oidc_jwks_file: str,
    console: Optional[Console] = None,
    config=None,
) -> Dict[str, Any]:
    """Run hypershift create iam gcp command and return the WIF configuration.

    Args:
        infra_id: Infrastructure ID for the cluster
        project_id: GCP project ID
        oidc_jwks_file: Path to OIDC JWKS file containing the public key
        console: Rich console for output (optional)
        config: Optional Config object to get hypershift binary path

    Returns:
        Dictionary containing the WIF configuration from hypershift

    Raises:
        HypershiftError: If hypershift command fails
    """
    if console:
        console.print("[cyan]Running hypershift create iam gcp...[/cyan]")
        console.print(f"  Infrastructure ID: {infra_id}")
        console.print(f"  Project ID: {project_id}")
        console.print(f"  OIDC JWKS File: {oidc_jwks_file}")

    # Get hypershift binary path
    hypershift_bin = get_hypershift_binary(config)
    if not hypershift_bin:
        raise HypershiftError(
            "hypershift CLI not found. Please install it or configure the path:\n"
            "  1. Install: https://hypershift-docs.netlify.app/getting-started/\n"
            "  2. Or set: gcphcp config set hypershift_binary /path/to/hypershift\n"
            "  3. Or set: export HYPERSHIFT_BINARY=/path/to/hypershift"
        )

    # Build the command
    cmd = [
        hypershift_bin,
        "create",
        "iam",
        "gcp",
        "--infra-id",
        infra_id,
        "--project-id",
        project_id,
        "--oidc-jwks-file",
        oidc_jwks_file,
    ]

    if console:
        console.print(f"[dim]Command: {' '.join(cmd)}[/dim]")

    try:
        # Run the command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            timeout=300,  # 5 minute timeout
        )

        # Parse the JSON output
        try:
            wif_config = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            raise HypershiftError(
                f"Failed to parse hypershift output as JSON: {e}\n"
                f"Output: {result.stdout}"
            )

        if console:
            console.print("[green]✓[/green] WIF infrastructure created successfully")

        return wif_config

    except subprocess.TimeoutExpired:
        raise HypershiftError("hypershift create iam gcp timed out after 5 minutes")
    except subprocess.CalledProcessError as e:
        error_msg = f"hypershift create iam gcp failed with exit code {e.returncode}"
        if e.stderr:
            error_msg += f"\nError: {e.stderr}"
        if e.stdout:
            error_msg += f"\nOutput: {e.stdout}"
        raise HypershiftError(error_msg)
    except Exception as e:
        raise HypershiftError(f"Unexpected error running hypershift: {e}")


def validate_wif_config(wif_config: Dict[str, Any]) -> bool:
    """Validate that the WIF configuration has all required fields.

    Args:
        wif_config: WIF configuration dictionary from hypershift

    Returns:
        True if valid, False otherwise
    """
    required_fields = [
        "projectId",
        "projectNumber",
        "infraId",
        "workloadIdentityPool",
        "serviceAccounts",
    ]

    for field in required_fields:
        if field not in wif_config:
            return False

    # Check nested fields
    if "poolId" not in wif_config.get("workloadIdentityPool", {}):
        return False
    if "providerId" not in wif_config.get("workloadIdentityPool", {}):
        return False

    service_accounts = wif_config.get("serviceAccounts", {})
    if "ctrlplane-op" not in service_accounts:
        return False
    if "nodepool-mgmt" not in service_accounts:
        return False

    return True


def wif_config_to_cluster_spec(wif_config: Dict[str, Any]) -> Dict[str, Any]:
    """Convert hypershift WIF config to cluster spec format.

    Args:
        wif_config: WIF configuration from hypershift create iam gcp

    Returns:
        Dictionary in the format expected by the cluster spec
    """
    pool = wif_config.get("workloadIdentityPool", {})
    service_accounts = wif_config.get("serviceAccounts", {})

    return {
        "projectNumber": wif_config.get("projectNumber"),
        "poolID": pool.get("poolId"),
        "providerID": pool.get("providerId"),
        "serviceAccountsRef": {
            "controlPlaneEmail": service_accounts.get("ctrlplane-op"),
            "nodePoolEmail": service_accounts.get("nodepool-mgmt"),
        },
    }
