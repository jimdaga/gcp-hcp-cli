"""Cryptographic utilities for key generation and management."""

import json
import base64
import hashlib
import tempfile
from typing import Tuple, NamedTuple
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend


class KeypairResult(NamedTuple):
    """Result of keypair generation."""

    private_key_pem: str
    private_key_pem_base64: str
    jwks_file_path: str
    kid: str  # Key ID calculated from DER-encoded public key

    def cleanup(self):
        """Clean up temporary files."""
        import os

        try:
            if self.jwks_file_path:
                os.unlink(self.jwks_file_path)
        except Exception:
            pass


def generate_cluster_keypair() -> KeypairResult:
    """Generate RSA keypair for cluster signing and create JWKS file.

    This function:
    1. Generates an RSA keypair (4096-bit, matching generate-sa-signing-key.sh)
    2. Converts private key to PEM format (PKCS#1/TraditionalOpenSSL)
    3. Base64-encodes the PEM for storage
    4. Converts public key to JWKS format using SHA256(DER) for kid
    5. Writes JWKS to a temporary file

    The key format and size match generate-sa-signing-key.sh:
    - 4096-bit RSA key
    - PKCS#1 format (BEGIN RSA PRIVATE KEY)
    - Generated with equivalent of 'openssl genrsa 4096' + 'openssl rsa -traditional'

    The kid (Key ID) is calculated using SHA256 hash of the DER-encoded public key,
    which is the industry-standard method used by Kubernetes and most OIDC providers.

    Returns:
        KeypairResult containing:
            - private_key_pem: PEM-encoded private key string (PKCS#1)
            - private_key_pem_base64: Base64-encoded PEM private key (for API)
            - jwks_file_path: Path to temporary JWKS file (caller should cleanup)
            - kid: Key ID (SHA256 hash of DER-encoded public key)

    Raises:
        Exception: If keypair generation or file operations fail
    """
    # Generate keypair
    private_key, public_key = generate_keypair()

    # Convert private key to PEM
    private_key_pem = private_key_to_pem(private_key)

    # Base64-encode the PEM for storage in backend
    private_key_pem_base64 = base64.b64encode(private_key_pem.encode("utf-8")).decode(
        "utf-8"
    )

    # Convert public key to JWKS (with kid calculated from DER)
    jwks_data, kid = public_key_to_jwks(public_key)

    # Write JWKS to temporary file
    jwks_file = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    jwks_file.write(jwks_data)
    jwks_file.close()

    return KeypairResult(
        private_key_pem=private_key_pem,
        private_key_pem_base64=private_key_pem_base64,
        jwks_file_path=jwks_file.name,
        kid=kid,
    )


def generate_keypair() -> Tuple[rsa.RSAPrivateKey, rsa.RSAPublicKey]:
    """Generate an RSA keypair for cluster signing.

    Generates a 4096-bit RSA keypair to match the requirements from
    generate-sa-signing-key.sh script.

    Returns:
        Tuple of (private_key, public_key)
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=4096,  # Match generate-sa-signing-key.sh
        backend=default_backend(),
    )
    public_key = private_key.public_key()
    return private_key, public_key


def private_key_to_pem(private_key: rsa.RSAPrivateKey) -> str:
    """Convert private key to PEM format string in PKCS#1 format.

    Uses TraditionalOpenSSL format (PKCS#1) to match generate-sa-signing-key.sh
    which uses 'openssl rsa -traditional'. This produces 'BEGIN RSA PRIVATE KEY'
    instead of 'BEGIN PRIVATE KEY' (PKCS#8).

    Args:
        private_key: RSA private key

    Returns:
        PEM-encoded private key as string in PKCS#1 format
    """
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,  # PKCS#1 format
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


def public_key_to_jwks(public_key: rsa.RSAPublicKey) -> Tuple[str, str]:
    """Convert public key to JWKS format JSON string.

    The kid (Key ID) is calculated using SHA256 hash of the DER-encoded public key,
    which matches the standard used by Kubernetes API server and most OIDC providers.

    Args:
        public_key: RSA public key

    Returns:
        Tuple of (JWKS format JSON string, kid)
    """
    # Get DER-encoded public key to calculate kid
    public_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    # Calculate kid from DER (SHA256 of DER-encoded public key)
    # This matches the standard used by Kubernetes
    kid = (
        base64.urlsafe_b64encode(hashlib.sha256(public_der).digest())
        .decode("utf-8")
        .rstrip("=")
    )

    # Get the public key numbers for n and e
    numbers = public_key.public_numbers()

    # Convert to base64url encoding (without padding)
    def int_to_base64url(num: int) -> str:
        # Convert int to bytes
        byte_length = (num.bit_length() + 7) // 8
        num_bytes = num.to_bytes(byte_length, byteorder="big")
        # Base64url encode without padding
        return base64.urlsafe_b64encode(num_bytes).rstrip(b"=").decode("utf-8")

    # Create JWKS structure
    jwks = {
        "keys": [
            {
                "use": "sig",
                "kty": "RSA",
                "kid": kid,
                "alg": "RS256",
                "n": int_to_base64url(numbers.n),
                "e": int_to_base64url(numbers.e),
            }
        ]
    }

    return json.dumps(jwks, indent=2), kid


def base64_encode_pem(pem_key: str) -> str:
    """Base64-encode a PEM key string.

    Args:
        pem_key: PEM-encoded key string

    Returns:
        Base64-encoded PEM key
    """
    return base64.b64encode(pem_key.encode("utf-8")).decode("utf-8")
