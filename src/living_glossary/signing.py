"""Sign and verify snapshot manifests with Ed25519.

Signing covers the manifest's existing SHA-256 checksums (already a canonical
digest of every table file: tampering with a Parquet file is caught by
`data.connect`'s checksum check). A signature over the manifest therefore
authenticates "snapshot.contents as listed", not the generated JSON byte stream
mechanically, which keeps verification stable across equivalent JSON formatting.

This proves the manifest was produced and signed by whoever holds the private
key; it does not independently establish that the key holder had collection
permission or reviewed the content. See PERMISSIONS.md.
"""
import base64
import json
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)


SIGNATURE_VERSION = 1


def generate_keypair() -> tuple[str, str]:
    """Return (private_key_b64, public_key_b64), both raw 32-byte Ed25519 keys."""
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    private_bytes = private_key.private_bytes(
        Encoding.Raw, PrivateFormat.Raw, NoEncryption()
    )
    public_bytes = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
    return (
        base64.b64encode(private_bytes).decode("ascii"),
        base64.b64encode(public_bytes).decode("ascii"),
    )


def _canonical_checksums(manifest: dict) -> bytes:
    checksums = {item["name"]: item["sha256"] for item in manifest["files"]}
    payload = {
        "schema_version": manifest["schema_version"],
        "version": manifest["version"],
        "files": dict(sorted(checksums.items())),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_manifest(snapshot: Path, private_key_b64: str) -> Path:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    private_key = Ed25519PrivateKey.from_private_bytes(
        base64.b64decode(private_key_b64)
    )
    signature = private_key.sign(_canonical_checksums(manifest))
    signature_path = snapshot / "manifest.sig.json"
    signature_path.write_text(
        json.dumps({
            "signature_version": SIGNATURE_VERSION,
            "algorithm": "ed25519",
            "signature": base64.b64encode(signature).decode("ascii"),
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return signature_path


def verify_manifest(snapshot: Path, public_key_b64: str) -> None:
    manifest_path = snapshot / "manifest.json"
    signature_path = snapshot / "manifest.sig.json"
    if not signature_path.exists():
        raise ValueError(f"No signature file found at {signature_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    envelope = json.loads(signature_path.read_text(encoding="utf-8"))
    if envelope.get("signature_version") != SIGNATURE_VERSION:
        raise ValueError("Unsupported signature format version")
    if envelope.get("algorithm") != "ed25519":
        raise ValueError("Unsupported signature algorithm")
    public_key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
    signature = base64.b64decode(envelope["signature"])
    try:
        public_key.verify(signature, _canonical_checksums(manifest))
    except InvalidSignature as error:
        raise ValueError("Signature does not match this manifest") from error
