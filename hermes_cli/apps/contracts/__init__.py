"""Versioned, frozen contracts for the local Hermes App Runtime."""

from importlib.resources import files
from pathlib import Path


CONTRACT_VERSION = "1.0.0"


def contract_directory() -> Path:
    """Return the packaged contract directory."""
    return Path(str(files(__package__)))


def contract_path(filename: str) -> Path:
    """Return one packaged contract path, rejecting nested lookups."""
    if not filename or Path(filename).name != filename:
        raise ValueError("contract filename must be a single path component")
    return contract_directory() / filename
__all__ = ["CONTRACT_VERSION", "contract_directory", "contract_path"]
