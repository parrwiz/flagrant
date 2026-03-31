"""Git helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from git import Repo, InvalidGitRepositoryError
from rich.console import Console

console = Console()


BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".exe", ".dll", ".so", ".dylib", ".o", ".a",
    ".pyc", ".pyo", ".class", ".wasm",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".sqlite", ".db",
}

def get_git_root(path: str = ".") -> Optional[Path]:
    """Find the git repo root from the given path."""
    try:
        repo = Repo(path, search_parent_directories=True)
        return Path(repo.working_dir)
    except InvalidGitRepositoryError:
        return None


def _is_binary_path(filepath: str) -> bool:
    """Check if a file is likely binary based on extension."""
    return Path(filepath).suffix.lower() in BINARY_EXTENSIONS


def _is_binary_content(filepath: Path) -> bool:
    """Check for null bytes."""
    try:
        with open(filepath, "rb") as f:
            chunk = f.read(8192)
            return b"\x00" in chunk
    except OSError:
        return True


def get_staged_diff(repo_path: str = ".") -> Optional[str]:
    """Get the unified diff of all staged changes."""
    try:
        repo = Repo(repo_path, search_parent_directories=True)
        diff = repo.git.diff("--cached", "--unified=3")
        return diff if diff.strip() else None
    except Exception:
        return None


def get_staged_files(repo_path: str = ".") -> list[dict]:
    """Get staged file contents. Skips binaries."""
    files = []
    try:
        repo = Repo(repo_path, search_parent_directories=True)
        root = Path(repo.working_dir)

        # Get list of staged file paths
        staged = repo.git.diff("--cached", "--name-only").strip()
        if not staged:
            return files

        for rel_path in staged.splitlines():
            rel_path = rel_path.strip()
            if not rel_path or _is_binary_path(rel_path):
                continue

            full_path = root / rel_path
            if not full_path.exists() or _is_binary_content(full_path):
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                files.append({"path": rel_path, "content": content})
            except OSError:
                continue

    except Exception:
        pass

    return files


def get_repo_files(
    path: str = ".",
    ignore_patterns: list[str] | None = None,
) -> list[dict]:
    """Get all tracked non-binary files in the repo."""
    files = []
    ignore_patterns = ignore_patterns or []

    try:
        repo = Repo(path, search_parent_directories=True)
        root = Path(repo.working_dir)

        tracked = repo.git.ls_files().strip()
        if not tracked:
            return files

        for rel_path in tracked.splitlines():
            rel_path = rel_path.strip()
            if not rel_path or _is_binary_path(rel_path):
                continue

            # Check ignore patterns
            if any(_matches_ignore(rel_path, pat) for pat in ignore_patterns):
                continue

            full_path = root / rel_path
            if not full_path.exists() or _is_binary_content(full_path):
                continue

            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                files.append({"path": rel_path, "content": content})
            except OSError:
                continue

    except Exception:
        pass

    return files


def read_single_file(filepath: str) -> Optional[dict]:
    """Read a single file, returning {path, content} or None."""
    p = Path(filepath)
    if not p.exists():
        return None
    if _is_binary_path(filepath) or _is_binary_content(p):
        return None
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "content": content}
    except OSError:
        return None


def _matches_ignore(filepath: str, pattern: str) -> bool:
    """Check if filepath matches an ignore pattern."""
    pattern = pattern.rstrip("/")
    return filepath.startswith(pattern) or f"/{pattern}" in filepath
