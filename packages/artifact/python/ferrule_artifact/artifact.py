import base64
import hashlib

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .canonical import canonicalize


def build(manifest: object | bytes | str) -> bytes:
    """Build an artifact as canonical manifest bytes."""
    return canonicalize(manifest)


def artifact_hash(artifact: bytes) -> str:
    """Hash an artifact previously produced by build()."""
    return "sha256:" + hashlib.sha256(artifact).hexdigest()


def _digest(artifact: bytes) -> bytes:
    return hashlib.sha256(artifact).digest()


def sign(artifact: bytes, private_key_pem: bytes) -> bytes:
    key = serialization.load_pem_private_key(private_key_pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("private key is not Ed25519")
    return key.sign(_digest(artifact))


def verify(artifact: bytes, signature: bytes, public_key_pem: bytes) -> bool:
    """Verify a detached signature, returning False for all invalid input."""
    if len(signature) != 64:
        return False
    try:
        key = serialization.load_pem_public_key(public_key_pem)
        if not isinstance(key, Ed25519PublicKey):
            return False
        key.verify(signature, _digest(artifact))
    except (InvalidSignature, TypeError, ValueError):
        return False
    return True


def generate_dev_keypair() -> tuple[bytes, bytes]:
    """Generate a local development keypair; production keys need managed custody."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def encode_signature(signature: bytes) -> str:
    return base64.b64encode(signature).decode("ascii")


def decode_signature(encoded: str) -> bytes | None:
    try:
        return base64.b64decode(encoded, validate=True)
    except ValueError:
        return None
