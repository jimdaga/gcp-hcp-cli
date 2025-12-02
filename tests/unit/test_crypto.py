"""Unit tests for crypto utilities."""

import base64
import json
import os

from gcphcp.utils.crypto import (
    KeypairResult,
    generate_keypair,
    private_key_to_pem,
    public_key_to_jwks,
    base64_encode_pem,
    generate_cluster_keypair,
)


class TestGenerateKeypair:
    """Tests for generate_keypair function."""

    def test_generate_keypair_returns_tuple(self):
        """When generating keypair it should return private and public keys."""
        private_key, public_key = generate_keypair()
        assert private_key is not None
        assert public_key is not None

    def test_generate_keypair_key_size(self):
        """When generating keypair it should use 4096-bit key size."""
        private_key, _ = generate_keypair()
        assert private_key.key_size == 4096

    def test_generate_keypair_public_exponent(self):
        """When generating keypair it should use 65537 as public exponent."""
        private_key, public_key = generate_keypair()
        assert public_key.public_numbers().e == 65537


class TestPrivateKeyToPem:
    """Tests for private_key_to_pem function."""

    def test_private_key_to_pem_format(self):
        """When converting to PEM it should use PKCS#1 format."""
        private_key, _ = generate_keypair()
        pem = private_key_to_pem(private_key)

        assert pem.startswith("-----BEGIN RSA PRIVATE KEY-----")
        assert pem.strip().endswith("-----END RSA PRIVATE KEY-----")

    def test_private_key_to_pem_returns_string(self):
        """When converting to PEM it should return a string."""
        private_key, _ = generate_keypair()
        pem = private_key_to_pem(private_key)

        assert isinstance(pem, str)


class TestPublicKeyToJwks:
    """Tests for public_key_to_jwks function."""

    def test_public_key_to_jwks_returns_tuple(self):
        """When converting to JWKS it should return json string and kid."""
        _, public_key = generate_keypair()
        jwks_json, kid = public_key_to_jwks(public_key)

        assert isinstance(jwks_json, str)
        assert isinstance(kid, str)

    def test_public_key_to_jwks_valid_json(self):
        """When converting to JWKS it should return valid JSON."""
        _, public_key = generate_keypair()
        jwks_json, _ = public_key_to_jwks(public_key)

        jwks = json.loads(jwks_json)
        assert "keys" in jwks
        assert len(jwks["keys"]) == 1

    def test_public_key_to_jwks_key_structure(self):
        """When converting to JWKS it should have correct key structure."""
        _, public_key = generate_keypair()
        jwks_json, kid = public_key_to_jwks(public_key)

        jwks = json.loads(jwks_json)
        key = jwks["keys"][0]

        assert key["kty"] == "RSA"
        assert key["use"] == "sig"
        assert key["alg"] == "RS256"
        assert key["kid"] == kid
        assert "n" in key
        assert "e" in key

    def test_public_key_to_jwks_kid_format(self):
        """When converting to JWKS it should generate URL-safe base64 kid."""
        _, public_key = generate_keypair()
        _, kid = public_key_to_jwks(public_key)

        # Kid should be URL-safe base64 without padding
        assert "+" not in kid
        assert "/" not in kid
        assert not kid.endswith("=")


class TestBase64EncodePem:
    """Tests for base64_encode_pem function."""

    def test_base64_encode_pem_roundtrip(self):
        """When encoding PEM it should be decodable back to original."""
        original_pem = (
            "-----BEGIN RSA PRIVATE KEY-----\ntest\n" "-----END RSA PRIVATE KEY-----"
        )
        encoded = base64_encode_pem(original_pem)
        decoded = base64.b64decode(encoded).decode("utf-8")

        assert decoded == original_pem

    def test_base64_encode_pem_returns_string(self):
        """When encoding PEM it should return a string."""
        pem = "test pem content"
        result = base64_encode_pem(pem)

        assert isinstance(result, str)


class TestKeypairResult:
    """Tests for KeypairResult named tuple."""

    def test_keypair_result_attributes(self):
        """When creating KeypairResult it should have all expected attributes."""
        result = KeypairResult(
            private_key_pem="pem",
            private_key_pem_base64="base64",
            jwks_file_path="/tmp/test.json",
            kid="test-kid",
        )

        assert result.private_key_pem == "pem"
        assert result.private_key_pem_base64 == "base64"
        assert result.jwks_file_path == "/tmp/test.json"
        assert result.kid == "test-kid"

    def test_keypair_result_cleanup_nonexistent_file(self):
        """When cleaning up non-existent file it should not raise error."""
        result = KeypairResult(
            private_key_pem="pem",
            private_key_pem_base64="base64",
            jwks_file_path="/nonexistent/path/test.json",
            kid="test-kid",
        )

        # Should not raise
        result.cleanup()


class TestGenerateClusterKeypair:
    """Tests for generate_cluster_keypair function."""

    def test_generate_cluster_keypair_returns_result(self):
        """When generating cluster keypair it should return KeypairResult."""
        result = generate_cluster_keypair()

        try:
            assert isinstance(result, KeypairResult)
            assert result.private_key_pem.startswith("-----BEGIN RSA PRIVATE KEY-----")
            assert len(result.private_key_pem_base64) > 0
            assert os.path.exists(result.jwks_file_path)
            assert len(result.kid) > 0
        finally:
            result.cleanup()

    def test_generate_cluster_keypair_jwks_file_valid(self):
        """When generating cluster keypair it should create valid JWKS file."""
        result = generate_cluster_keypair()

        try:
            with open(result.jwks_file_path, "r") as f:
                jwks = json.load(f)

            assert "keys" in jwks
            assert len(jwks["keys"]) == 1
            assert jwks["keys"][0]["kid"] == result.kid
        finally:
            result.cleanup()

    def test_generate_cluster_keypair_base64_decodable(self):
        """When generating cluster keypair the base64 PEM should be decodable."""
        result = generate_cluster_keypair()

        try:
            decoded = base64.b64decode(result.private_key_pem_base64).decode("utf-8")
            assert decoded == result.private_key_pem
        finally:
            result.cleanup()
