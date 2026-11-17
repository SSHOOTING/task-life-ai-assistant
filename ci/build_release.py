#!/usr/bin/env python3
"""Build a deterministic deployment archive for the MVP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "dist" / "goal-of-ours-mvp.zip"
DEFAULT_METADATA = PROJECT_ROOT / "dist" / "release-metadata.json"
INCLUDE_ROOTS = ("mvp", "deploy/bluepc")
EXCLUDED_DIR_NAMES = {
    ".git",
    ".github",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "env",
    "node_modules",
    "venv",
}
EXCLUDED_SUFFIXES = {
    ".bak",
    ".db",
    ".db-journal",
    ".db-shm",
    ".db-wal",
    ".key",
    ".log",
    ".pem",
    ".pid",
    ".pyc",
    ".pyo",
    ".sqlite",
    ".sqlite3",
    ".swp",
    ".temp",
    ".tmp",
}
EXCLUDED_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    "credentials.json",
    "secrets.json",
}
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
TEXT_SUFFIXES = {
    ".cfg",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}


def _is_excluded(relative_path: Path) -> bool:
    if any(part in EXCLUDED_DIR_NAMES for part in relative_path.parts[:-1]):
        return True
    name = relative_path.name
    if name in EXCLUDED_NAMES:
        return True
    if name == ".env" or name.startswith(".env."):
        return True
    return relative_path.suffix.lower() in EXCLUDED_SUFFIXES


def _release_files(project_root: Path) -> list[tuple[str, Path]]:
    root = project_root.resolve()
    files: list[tuple[str, Path]] = []
    for include_root in INCLUDE_ROOTS:
        candidate = (root / include_root).resolve()
        if root not in candidate.parents:
            raise ValueError(f"include root escapes project: {include_root}")
        if not candidate.exists():
            raise FileNotFoundError(f"required release path is missing: {include_root}")
        if candidate.is_file():
            paths = [candidate]
        else:
            paths = sorted(path for path in candidate.rglob("*") if path.is_file())
        for path in paths:
            resolved = path.resolve()
            if root not in resolved.parents:
                raise ValueError(f"release file escapes project: {path}")
            if path.is_symlink():
                raise ValueError(f"release archive does not accept symlinks: {path}")
            relative = path.relative_to(root)
            if not _is_excluded(relative):
                files.append((relative.as_posix(), path))
    unique = {archive_name: path for archive_name, path in files}
    if not any(name == "mvp/app.py" for name in unique):
        raise FileNotFoundError("release archive must contain mvp/app.py")
    return sorted(unique.items(), key=lambda item: item[0])


def _zip_info(archive_name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(archive_name, date_time=FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o644) << 16
    info.flag_bits |= 0x800
    return info


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if path.suffix.lower() in TEXT_SUFFIXES:
        return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def build_release(
    *,
    project_root: Path = PROJECT_ROOT,
    output: Path = DEFAULT_OUTPUT,
    metadata: Path = DEFAULT_METADATA,
    release_id: str = "local",
) -> dict:
    project_root = project_root.resolve()
    output = output.resolve()
    metadata = metadata.resolve()
    files = _release_files(project_root)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    if temporary.exists():
        temporary.unlink()
    try:
        with zipfile.ZipFile(
            temporary,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for archive_name, source in files:
                info = _zip_info(archive_name)
                archive.writestr(info, _archive_bytes(source))
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()

    archive_sha256 = _sha256(output)
    checksum_path = output.with_name(f"{output.name}.sha256")
    checksum_path.write_text(
        f"{archive_sha256}  {output.name}\n",
        encoding="ascii",
        newline="\n",
    )

    entries = [
        {
            "path": archive_name,
            "size_bytes": len(_archive_bytes(source)),
            "sha256": hashlib.sha256(_archive_bytes(source)).hexdigest(),
        }
        for archive_name, source in files
    ]
    payload = {
        "format_version": 1,
        "release_id": release_id,
        "archive": output.name,
        "archive_sha256": archive_sha256,
        "archive_size_bytes": output.stat().st_size,
        "file_count": len(entries),
        "files": entries,
    }
    metadata.parent.mkdir(parents=True, exist_ok=True)
    metadata.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return payload


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, deployment-ready MVP zip."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--release-id", default="local")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Project root to package; useful for local verification.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = build_release(
            project_root=args.project_root,
            output=args.output,
            metadata=args.metadata,
            release_id=args.release_id,
        )
    except (FileNotFoundError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"release build failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"built {result['archive']} "
        f"({result['file_count']} files, {result['archive_size_bytes']} bytes)"
    )
    print(f"sha256 {result['archive_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
