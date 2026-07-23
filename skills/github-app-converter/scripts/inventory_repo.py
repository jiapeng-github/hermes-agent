#!/usr/bin/env python3
"""Create a bounded, read-only inventory of an untrusted source repository."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".output",
    ".svelte-kit",
    ".venv",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
    "venv",
}
TEXT_SUFFIXES = {
    ".css",
    ".html",
    ".htm",
    ".js",
    ".jsx",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".rs",
    ".scss",
    ".svelte",
    ".toml",
    ".ts",
    ".tsx",
    ".vue",
    ".yaml",
    ".yml",
}
FRONTEND_ENTRY_NAMES = {
    "index.html",
    "src/app.tsx",
    "src/app.jsx",
    "src/main.ts",
    "src/main.tsx",
    "src/main.js",
    "src/main.jsx",
    "pages/index.tsx",
    "app/page.tsx",
}
LIFECYCLE_SCRIPTS = {"preinstall", "install", "postinstall", "prepare"}
LICENSE_NAMES = {
    "license",
    "license.md",
    "license.txt",
    "copying",
    "copying.md",
    "copying.txt",
    "notice",
    "notice.md",
    "notice.txt",
}
URL_RE = re.compile(r"https?://[^\s\"'<>`)]+", re.IGNORECASE)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_credential_like(path: str) -> bool:
    name = Path(path).name.lower()
    if name == ".env" or name.startswith(".env."):
        return not name.endswith((".example", ".sample", ".template"))
    if name.endswith((".pem", ".p12", ".pfx", ".key", ".keystore")):
        return True
    return name in {
        "credentials.json",
        "service-account.json",
        "secrets.json",
        "id_rsa",
        "id_ed25519",
    }


def _safe_origin(raw_url: str) -> str | None:
    try:
        parsed = urlsplit(raw_url.rstrip(".,;:"))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{parsed.hostname.lower()}{port}"


def _read_text(path: Path, limit: int) -> str | None:
    try:
        if path.stat().st_size > limit:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data:
        return None
    return data.decode("utf-8", errors="replace")


def _read_json(path: Path, limit: int) -> dict[str, Any] | None:
    text = _read_text(path, limit)
    if text is None:
        return None
    try:
        value = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def inventory_repository(root: Path, *, max_files: int = 5000, max_text_bytes: int = 262_144) -> dict[str, Any]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")

    files: list[str] = []
    symlinks: list[str] = []
    credential_paths: list[str] = []
    remote_origins: set[str] = set()
    scanned_text_files = 0
    truncated = False

    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        dirnames[:] = sorted(
            name for name in dirnames if name not in SKIP_DIRS and not (current_path / name).is_symlink()
        )
        for name in sorted(filenames):
            path = current_path / name
            rel = _relative(path, root)
            if len(files) >= max_files:
                truncated = True
                break
            files.append(rel)
            if path.is_symlink():
                symlinks.append(rel)
                continue
            if _is_credential_like(rel):
                credential_paths.append(rel)
                continue
            if path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            text = _read_text(path, max_text_bytes)
            if text is None:
                continue
            scanned_text_files += 1
            for match in URL_RE.findall(text):
                origin = _safe_origin(match)
                if origin:
                    remote_origins.add(origin)
        if truncated:
            break

    file_set = set(files)
    package_json = _read_json(root / "package.json", max_text_bytes) if "package.json" in file_set else None
    dependencies: set[str] = set()
    package_scripts: list[str] = []
    if package_json:
        for key in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            values = package_json.get(key)
            if isinstance(values, dict):
                dependencies.update(str(name).lower() for name in values)
        scripts = package_json.get("scripts")
        if isinstance(scripts, dict):
            package_scripts = sorted(str(name) for name in scripts)

    frameworks: set[str] = set()
    dependency_frameworks = {
        "@angular/core": "angular",
        "@sveltejs/kit": "sveltekit",
        "@tauri-apps/api": "tauri",
        "electron": "electron",
        "next": "nextjs",
        "nuxt": "nuxt",
        "react": "react",
        "svelte": "svelte",
        "vite": "vite",
        "vue": "vue",
    }
    for dependency, framework in dependency_frameworks.items():
        if dependency in dependencies:
            frameworks.add(framework)
    if "Cargo.toml" in file_set and any(path.startswith("src-tauri/") for path in file_set):
        frameworks.add("tauri")

    frontend_entries = sorted(path for path in file_set if path.lower() in FRONTEND_ENTRY_NAMES)
    frontend_entries.extend(
        sorted(
            path
            for path in file_set
            if path not in frontend_entries and Path(path).name.lower() == "index.html"
        )
    )

    backend_markers: set[str] = set()
    backend_dirs = ("api/", "backend/", "server/", "functions/", "lambda/")
    for path in file_set:
        lower = path.lower()
        if lower.startswith(backend_dirs):
            backend_markers.add(path.split("/", 1)[0] + "/")
    backend_dependencies = {
        "@nestjs/core",
        "express",
        "fastify",
        "flask",
        "django",
        "fastapi",
        "hono",
        "koa",
    }
    backend_markers.update(sorted(dependencies & backend_dependencies))
    if any(path in file_set for path in ("requirements.txt", "pyproject.toml", "Pipfile")):
        backend_markers.add("python-project")

    license_files = sorted(path for path in file_set if Path(path).name.lower() in LICENSE_NAMES)
    submodule_files = sorted(path for path in file_set if Path(path).name == ".gitmodules")
    lfs_pointers = sorted(path for path in file_set if path == ".gitattributes")
    lifecycle_scripts = sorted(set(package_scripts) & LIFECYCLE_SCRIPTS)

    risk_markers: list[dict[str, Any]] = []
    if credential_paths:
        risk_markers.append({"code": "credential_like_paths", "count": len(credential_paths)})
    if lifecycle_scripts:
        risk_markers.append({"code": "package_lifecycle_scripts", "names": lifecycle_scripts})
    if backend_markers:
        risk_markers.append({"code": "backend_present", "count": len(backend_markers)})
    if symlinks:
        risk_markers.append({"code": "symlinks_present", "count": len(symlinks)})
    if submodule_files:
        risk_markers.append({"code": "git_submodules_declared"})
    if remote_origins:
        risk_markers.append({"code": "remote_origins_present", "count": len(remote_origins)})
    if not license_files:
        risk_markers.append({"code": "license_not_found"})
    if truncated:
        risk_markers.append({"code": "inventory_truncated", "max_files": max_files})

    if credential_paths or not license_files:
        suggested_class = "D"
    elif backend_markers:
        suggested_class = "B"
    elif frontend_entries:
        suggested_class = "A"
    else:
        suggested_class = "C"

    return {
        "schema_version": 1,
        "files_scanned": len(files),
        "text_files_scanned": scanned_text_files,
        "truncated": truncated,
        "frameworks": sorted(frameworks),
        "frontend_entries": sorted(set(frontend_entries)),
        "backend_markers": sorted(backend_markers),
        "package_scripts": package_scripts,
        "lifecycle_scripts": lifecycle_scripts,
        "credential_like_paths": sorted(credential_paths),
        "symlinks": sorted(symlinks),
        "remote_origins": sorted(remote_origins),
        "license_files": license_files,
        "submodule_files": submodule_files,
        "lfs_metadata_files": lfs_pointers,
        "risk_markers": risk_markers,
        "suggested_class": suggested_class,
        "notice": "Read-only heuristic inventory; manual source, license, and security review is required.",
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path, help="Path to an already checked-out repository")
    parser.add_argument("--json", action="store_true", help="Print stable JSON output")
    parser.add_argument("--max-files", type=int, default=5000)
    parser.add_argument("--max-text-bytes", type=int, default=262_144)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.max_files < 1 or args.max_text_bytes < 1:
        print("Limits must be positive integers.", file=sys.stderr)
        return 2
    try:
        report = inventory_repository(
            args.repository,
            max_files=args.max_files,
            max_text_bytes=args.max_text_bytes,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(f"Suggested class: {report['suggested_class']}")
        print(f"Files scanned: {report['files_scanned']}")
        print(f"Frameworks: {', '.join(report['frameworks']) or 'unknown'}")
        print(f"Risk markers: {len(report['risk_markers'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
