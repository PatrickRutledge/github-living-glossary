from pathlib import Path

import pytest

from living_glossary.data import build
from living_glossary.signing import generate_keypair, sign_manifest, verify_manifest


SAMPLE = Path(__file__).resolve().parents[1] / "data/sample"


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snapshot"
    build(SAMPLE, path)
    return path


def test_sign_and_verify_round_trip(snapshot):
    private_key, public_key = generate_keypair()
    sign_manifest(snapshot, private_key)
    verify_manifest(snapshot, public_key)  # does not raise


def test_verify_rejects_wrong_key(snapshot):
    private_key, _ = generate_keypair()
    _, other_public_key = generate_keypair()
    sign_manifest(snapshot, private_key)
    with pytest.raises(ValueError, match="does not match"):
        verify_manifest(snapshot, other_public_key)


def test_verify_rejects_tampered_checksum(snapshot):
    private_key, public_key = generate_keypair()
    sign_manifest(snapshot, private_key)
    manifest_path = snapshot / "manifest.json"
    import json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="does not match"):
        verify_manifest(snapshot, public_key)


def test_verify_missing_signature(snapshot):
    _, public_key = generate_keypair()
    with pytest.raises(ValueError, match="No signature file"):
        verify_manifest(snapshot, public_key)


def test_keypair_is_base64_32_bytes():
    import base64
    private_key, public_key = generate_keypair()
    assert len(base64.b64decode(private_key)) == 32
    assert len(base64.b64decode(public_key)) == 32
