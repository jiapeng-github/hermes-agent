from __future__ import annotations

import stat
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from hermes_cli.apps.errors import PackageTooLargeError, PackageValidationError
from hermes_cli.apps.package import SigningKey, inspect_happ_package

from .happ_fixtures import build_happ, manifest_data


def _inspect(package: Path, tmp_path: Path):
    return inspect_happ_package(package, tmp_path / "extracted")


def test_valid_unsigned_package_is_fully_verified(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "watchlist.happ")

    inspection = _inspect(package, tmp_path)

    assert inspection.manifest.id == "ai.hermes.watchlist"
    assert inspection.envelope.source_included is True
    assert inspection.signature_state == "unsigned"
    assert (tmp_path / "extracted/dist/index.html").is_file()


@pytest.mark.parametrize(
    "hostile_path",
    [
        "../escape.txt",
        "/absolute.txt",
        "source/../../escape.txt",
        "source\\escape.txt",
        "source/CON.txt",
    ],
)
def test_archive_path_attacks_are_rejected(tmp_path: Path, hostile_path: str) -> None:
    package = build_happ(
        tmp_path / "hostile.happ",
        extra_files={hostile_path: b"owned"},
    )

    with pytest.raises(PackageValidationError):
        _inspect(package, tmp_path)

    assert not (tmp_path / "escape.txt").exists()


def test_symlink_member_is_rejected_before_extraction(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "symlink.happ",
        extra_files={"source/link": b"../../outside"},
        member_modes={"source/link": stat.S_IFLNK | 0o777},
    )

    with pytest.raises(PackageValidationError, match="link or special"):
        _inspect(package, tmp_path)


def test_case_colliding_member_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "collision.happ",
        extra_files={"assets/Chart.js": b"one"},
        duplicate_files=[("assets/chart.js", b"two")],
    )

    with pytest.raises(PackageValidationError, match="case-colliding"):
        _inspect(package, tmp_path)


def test_file_directory_prefix_collision_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "prefix.happ",
        extra_files={"assets/chart": b"file", "assets/chart/data.json": b"{}"},
    )

    with pytest.raises(PackageValidationError, match="also used as a directory"):
        _inspect(package, tmp_path)


def test_compression_bomb_ratio_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "bomb.happ",
        extra_files={"assets/bomb.txt": b"0" * (2 * 1024 * 1024)},
    )

    with pytest.raises(PackageTooLargeError, match="excessively compressed"):
        _inspect(package, tmp_path)


def test_checksum_mismatch_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "checksum.happ",
        checksum_override={"dist/index.html": "0" * 64},
    )

    with pytest.raises(PackageValidationError, match="checksum mismatch"):
        _inspect(package, tmp_path)


def test_noncanonical_checksum_metadata_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "pretty.happ",
        canonical_checksums=False,
    )

    with pytest.raises(PackageValidationError, match="canonical"):
        _inspect(package, tmp_path)


@pytest.mark.parametrize(
    "server_file",
    ["source/server.py", "source/start.sh", "dist/native.dylib"],
)
def test_custom_server_code_is_rejected(tmp_path: Path, server_file: str) -> None:
    package = build_happ(
        tmp_path / "backend.happ",
        extra_files={server_file: b"code"},
    )

    with pytest.raises(PackageValidationError, match="server-side code"):
        _inspect(package, tmp_path)


def test_executable_regular_file_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "executable.happ",
        extra_files={"source/build.js": b"code"},
        member_modes={"source/build.js": stat.S_IFREG | 0o700},
    )

    with pytest.raises(PackageValidationError, match="cannot be executable"):
        _inspect(package, tmp_path)


def test_trailing_archive_data_is_rejected(tmp_path: Path) -> None:
    package = build_happ(tmp_path / "trailing.happ")
    with package.open("ab") as handle:
        handle.write(b"stolen-token")

    with pytest.raises(PackageValidationError, match="trailing data"):
        _inspect(package, tmp_path)


def test_trusted_ed25519_signature_is_verified(tmp_path: Path) -> None:
    private_key = Ed25519PrivateKey.generate()
    package = build_happ(
        tmp_path / "signed.happ",
        signing_key=("official-test", private_key),
    )
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )

    inspection = inspect_happ_package(
        package,
        tmp_path / "signed-extracted",
        signing_keys={"official-test": SigningKey(public_key, trusted=True)},
    )

    assert inspection.signature_state == "valid_trusted"


def test_unknown_signature_key_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "unknown-key.happ",
        signing_key=("unknown", Ed25519PrivateKey.generate()),
    )

    with pytest.raises(PackageValidationError, match="unknown signing key"):
        inspect_happ_package(package, tmp_path / "unknown-extracted")


def test_imported_manifest_cannot_smuggle_service_handler(tmp_path: Path) -> None:
    manifest = manifest_data()
    manifest["actions"] = {
        "snapshot": {
            "kind": "service",
            "title": "快照",
            "handler": "finance.watchlist.snapshot",
            "input_schema": "schemas/refresh.input.json",
            "output_schema": "schemas/refresh.output.json",
            "timeout_seconds": 30,
            "max_concurrent_runs": 1,
            "cache_ttl_seconds": 10,
        }
    }
    package = build_happ(tmp_path / "service.happ", manifest=manifest)

    with pytest.raises(PackageValidationError, match="forbidden capability"):
        _inspect(package, tmp_path)


def test_manifest_cannot_smuggle_backend_configuration(tmp_path: Path) -> None:
    manifest = manifest_data()
    manifest["backend"] = {"command": "python server.py"}
    package = build_happ(tmp_path / "backend-field.happ", manifest=manifest)

    with pytest.raises(PackageValidationError, match="Manifest is invalid"):
        _inspect(package, tmp_path)


@pytest.mark.parametrize(
    "secret_path",
    [
        "source/.env",
        "source/.env.production",
        "source/.npmrc",
        "assets/private.pem",
        "source/credentials.json",
    ],
)
def test_credential_like_files_are_rejected(tmp_path: Path, secret_path: str) -> None:
    package = build_happ(
        tmp_path / "secret.happ",
        extra_files={secret_path: b"SECRET=value"},
    )

    with pytest.raises(PackageValidationError, match="credential-like"):
        _inspect(package, tmp_path)


def test_runtime_data_root_is_rejected(tmp_path: Path) -> None:
    package = build_happ(
        tmp_path / "runtime-data.happ",
        extra_files={"app-data/watchlist.json": b"[]"},
    )

    with pytest.raises(PackageValidationError, match="allowed root"):
        _inspect(package, tmp_path)
