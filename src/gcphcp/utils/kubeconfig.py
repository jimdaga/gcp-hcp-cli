"""Kubeconfig manipulation utilities (oc-style implementation)."""

import base64
import json
import os
import shutil
import subprocess
import warnings
from typing import Dict, Any, Optional, Tuple

import requests
import urllib3
import yaml


class KubeconfigError(Exception):
    """Exception raised when kubeconfig operations fail."""

    pass


def get_oc_binary(config=None) -> Optional[str]:
    """Get the path to the oc binary.

    Checks in order:
    1. OC_BINARY environment variable
    2. oc_binary config setting (if config provided)
    3. 'oc' in PATH

    Args:
        config: Optional Config object to check for oc_binary setting

    Returns:
        Path to oc binary or None if not found
    """
    # Check environment variable first
    env_binary = os.environ.get("OC_BINARY")
    if env_binary and os.path.isfile(env_binary):
        return env_binary

    # Check config if provided
    if config:
        config_binary = getattr(config, "get_oc_binary", lambda: None)()
        if config_binary and os.path.isfile(config_binary):
            return config_binary

    # Check in PATH
    path_binary = shutil.which("oc")
    if path_binary:
        return path_binary

    return None


def check_oc_installed(config=None) -> bool:
    """Check if oc CLI is installed and available.

    Args:
        config: Optional Config object to check for oc_binary setting

    Returns:
        True if oc is installed, False otherwise
    """
    return get_oc_binary(config) is not None


def login_with_oc(
    server: str,
    token: str,
    kubeconfig_path: Optional[str] = None,
    insecure_skip_tls_verify: bool = True,
    config=None,
) -> Tuple[bool, str]:
    """Login to cluster using oc CLI.

    Args:
        server: API server URL
        token: Bearer token for authentication
        kubeconfig_path: Optional path to kubeconfig file
        insecure_skip_tls_verify: Skip TLS verification
        config: Optional Config object to check for oc_binary setting

    Returns:
        Tuple of (success, message)

    Raises:
        KubeconfigError: If oc command fails
    """
    oc_bin = get_oc_binary(config)
    if not oc_bin:
        raise KubeconfigError("oc CLI not found")

    cmd = [
        oc_bin,
        "login",
        "--token",
        token,
        "--server",
        server,
    ]

    if insecure_skip_tls_verify:
        cmd.append("--insecure-skip-tls-verify")

    if kubeconfig_path:
        cmd.extend(["--kubeconfig", kubeconfig_path])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            raise KubeconfigError(f"oc login failed: {error_msg}")

        return True, result.stdout.strip()

    except subprocess.TimeoutExpired:
        raise KubeconfigError("oc login timed out")
    except KubeconfigError:
        raise
    except subprocess.SubprocessError as e:
        raise KubeconfigError(f"oc login failed: {e}")


def validate_token(
    server: str,
    token: str,
    insecure_skip_tls_verify: bool = True,
) -> Dict[str, Any]:
    """Validate token against cluster API server.

    Args:
        server: API server URL
        token: Bearer token for authentication
        insecure_skip_tls_verify: Skip TLS verification

    Returns:
        Dict with user info extracted from token

    Raises:
        KubeconfigError: If validation fails
    """
    try:
        # Suppress InsecureRequestWarning when TLS verification is disabled
        with warnings.catch_warnings():
            if insecure_skip_tls_verify:
                warnings.filterwarnings(
                    "ignore", category=urllib3.exceptions.InsecureRequestWarning
                )
            response = requests.get(
                f"{server}/api",
                headers={"Authorization": f"Bearer {token}"},
                verify=not insecure_skip_tls_verify,
                timeout=10,
            )

        if response.status_code == 401:
            raise KubeconfigError("Authentication failed: Invalid or expired token")

        if response.status_code == 403:
            # 403 means authenticated but not authorized for /api
            # This is actually OK - token is valid
            pass
        elif not response.ok:
            raise KubeconfigError(
                f"Connection failed: {response.status_code} {response.reason}"
            )

    except requests.exceptions.SSLError as e:
        raise KubeconfigError(f"SSL error: {e}. Try with --insecure flag.")
    except requests.exceptions.ConnectionError:
        raise KubeconfigError(f"Connection error: Cannot reach {server}")
    except requests.exceptions.Timeout:
        raise KubeconfigError(f"Connection timeout: {server}")

    # Extract user info from token (decode JWT without verification)
    return _decode_token_claims(token)


def _decode_token_claims(token: str) -> Dict[str, Any]:
    """Decode JWT token claims without verification.

    Args:
        token: JWT token string

    Returns:
        Dict with token claims (email, hd, sub, etc.), or empty dict on error
    """
    try:
        # JWT format: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return {}

        # Decode payload (add padding if needed)
        payload = parts[1]
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        decoded = base64.urlsafe_b64decode(payload)
        claims = json.loads(decoded)

        return {
            "email": claims.get("email", "unknown"),
            "hd": claims.get("hd"),  # hosted domain
            "sub": claims.get("sub"),
        }
    except Exception:
        return {}


def update_kubeconfig(
    cluster_name: str,
    server: str,
    token: str,
    namespace: str = "default",
    kubeconfig_path: Optional[str] = None,
    insecure_skip_tls_verify: bool = True,
) -> str:
    """Update kubeconfig with cluster credentials (oc-style).

    This follows the same pattern as 'oc login --token':
    - Adds/updates cluster entry
    - Adds/updates user entry with token
    - Adds/updates context
    - Sets current-context

    Args:
        cluster_name: Name for the cluster/context
        server: API server URL
        token: Bearer token for authentication
        namespace: Default namespace for context
        kubeconfig_path: Path to kubeconfig file (default: ~/.kube/config)
        insecure_skip_tls_verify: Skip TLS verification

    Returns:
        Context name that was set

    Raises:
        KubeconfigError: If kubeconfig update fails
    """
    kubeconfig_path = (
        kubeconfig_path
        or os.environ.get("KUBECONFIG")
        or os.path.expanduser("~/.kube/config")
    )

    # Load existing kubeconfig or create new
    if os.path.exists(kubeconfig_path):
        try:
            with open(kubeconfig_path) as f:
                kc = yaml.safe_load(f) or {}
        except Exception as e:
            raise KubeconfigError(f"Failed to load kubeconfig: {e}")
    else:
        kc = {}

    # Ensure required structure
    kc.setdefault("apiVersion", "v1")
    kc.setdefault("kind", "Config")
    kc.setdefault("clusters", [])
    kc.setdefault("users", [])
    kc.setdefault("contexts", [])
    kc.setdefault("preferences", {})

    # Build context name (similar to oc)
    context_name = f"{namespace}/{cluster_name}"

    # Cluster entry
    cluster_config: Dict[str, Any] = {"server": server}
    if insecure_skip_tls_verify:
        cluster_config["insecure-skip-tls-verify"] = True

    cluster_entry = {
        "name": cluster_name,
        "cluster": cluster_config,
    }

    # User entry - use exec-based auth for fresh tokens
    user_entry = {
        "name": cluster_name,
        "user": {
            "exec": {
                "apiVersion": "client.authentication.k8s.io/v1beta1",
                "command": "bash",
                "args": [
                    "-c",
                    "cat <<EOT\n"
                    "{\n"
                    '  "apiVersion": "client.authentication.k8s.io/v1beta1",\n'
                    '  "kind": "ExecCredential",\n'
                    '  "status": {\n'
                    '    "token": "$(gcloud auth print-identity-token)"\n'
                    "  }\n"
                    "}\n"
                    "EOT",
                ],
                "interactiveMode": "Never",
            },
        },
    }

    # Context entry
    context_entry = {
        "name": context_name,
        "context": {
            "cluster": cluster_name,
            "user": cluster_name,
            "namespace": namespace,
        },
    }

    # Upsert entries
    _upsert_by_name(kc["clusters"], cluster_entry)
    _upsert_by_name(kc["users"], user_entry)
    _upsert_by_name(kc["contexts"], context_entry)

    # Set current context
    kc["current-context"] = context_name

    # Write kubeconfig
    try:
        os.makedirs(os.path.dirname(kubeconfig_path), exist_ok=True)
        with open(kubeconfig_path, "w") as f:
            yaml.dump(kc, f, default_flow_style=False, sort_keys=False)
    except Exception as e:
        raise KubeconfigError(f"Failed to write kubeconfig: {e}")

    return context_name


def _upsert_by_name(items: list, new_item: dict) -> None:
    """Update item if exists by name, otherwise append.

    Args:
        items: List of items with 'name' field
        new_item: New item to upsert
    """
    name = new_item["name"]
    for i, item in enumerate(items):
        if item.get("name") == name:
            items[i] = new_item
            return
    items.append(new_item)


def get_google_id_token() -> str:
    """Get Google ID token using gcloud CLI.

    Returns:
        ID token string

    Raises:
        KubeconfigError: If token retrieval fails
    """
    gcloud_bin = shutil.which("gcloud")
    if not gcloud_bin:
        raise KubeconfigError("gcloud CLI not found. Please install Google Cloud SDK.")

    try:
        result = subprocess.run(
            [gcloud_bin, "auth", "print-identity-token"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or "Unknown error"
            raise KubeconfigError(
                f"Failed to get Google token: {error_msg}\n"
                "Run 'gcloud auth login' first."
            )

        token = result.stdout.strip()
        if not token:
            raise KubeconfigError("No token returned. Run 'gcloud auth login' first.")

        return token

    except subprocess.TimeoutExpired:
        raise KubeconfigError("gcloud auth timed out")
    except Exception as e:
        if isinstance(e, KubeconfigError):
            raise
        raise KubeconfigError(f"Failed to get Google token: {e}")
