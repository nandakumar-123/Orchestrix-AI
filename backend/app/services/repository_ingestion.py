import base64
import fnmatch
import logging
import os
from typing import Any

import httpx

security_logger = logging.getLogger("orchestrix.security")

# Resource & Size Guardrails
MAX_FILE_SIZE_BYTES = 500 * 1024  # 500 KB limit per file to avoid RAM bloat
MAX_REPOSITORY_FILES = 2000  # Cap on total files processed per repository

# Excluded Directory Patterns
EXCLUDED_DIRECTORIES = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "__pycache__",
    "dist",
    "build",
    "out",
    ".next",
    "target",
    "bin",
    "obj",
    ".turbo",
    ".gradle",
    ".idea",
    ".vscode",
    "coverage",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
}

# Excluded Binary & Media File Extensions
BINARY_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".webp",
    ".bmp",
    ".tiff",
    ".pdf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".7z",
    ".rar",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".class",
    ".jar",
    ".war",
    ".pyc",
    ".pyo",
    ".wasm",
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".sqlite",
    ".db",
    ".bin",
    ".iso",
    ".dmg",
}

# Secret & Sensitive File Patterns (Never ingest contents into repository intelligence)
SECRET_PATTERNS = [
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.pfx",
    "*.p12",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "credentials.json",
    "client_secret*.json",
    "service_account*.json",
    "*_token.json",
]

# Language Extension Mapping
LANGUAGE_MAP: dict[str, str] = {
    ".py": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JSX",
    ".ts": "TypeScript",
    ".tsx": "TSX",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hxx": "C++",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".xml": "XML",
    ".sql": "SQL",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "SCSS",
}

# Known Dependency Manifest Filenames
MANIFEST_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Pipfile",
    "composer.json",
}


def is_path_safe(path: str) -> bool:
    """Validate that path does not attempt directory traversal."""
    normalized = os.path.normpath(path).replace("\\", "/")
    if normalized.startswith("../") or "/../" in normalized or normalized == "..":
        return False
    return not os.path.isabs(normalized)


def is_secret_file(filename: str) -> bool:
    """Check if file matches sensitive secret or credential naming patterns."""
    basename = os.path.basename(filename).lower()
    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(basename, pattern.lower()):
            return True
    return False


def should_skip_file(path: str, size: int = 0) -> tuple[bool, str]:
    """
    Determine if a file in the Git tree should be excluded from code intelligence.
    Returns (should_skip, reason).
    """
    if not is_path_safe(path):
        return True, "path_traversal_unsafe"

    parts = path.split("/")
    # Check directory exclusions
    for part in parts[:-1]:
        if part in EXCLUDED_DIRECTORIES or part.startswith("."):
            return True, f"excluded_directory:{part}"

    filename = parts[-1]
    if is_secret_file(filename):
        return True, "secret_file_excluded"

    _, ext = os.path.splitext(filename)
    ext_lower = ext.lower()
    if ext_lower in BINARY_EXTENSIONS:
        return True, "binary_file_skipped"

    if size > MAX_FILE_SIZE_BYTES:
        return True, f"file_size_exceeded:{size}B"

    return False, "ok"


def detect_language(path: str) -> str | None:
    """Detect programming language from file extension or manifest name."""
    basename = os.path.basename(path).lower()
    if basename in ("dockerfile", "makefile", "cmakelists.txt"):
        return basename.capitalize()
    _, ext = os.path.splitext(path)
    return LANGUAGE_MAP.get(ext.lower())


def is_manifest_file(path: str) -> bool:
    """Check if file is a recognized dependency manifest."""
    basename = os.path.basename(path).lower()
    return basename in {m.lower() for m in MANIFEST_FILENAMES}


# -----------------------------------------------------------------------------
# GitHub API Operations for Repository Ingestion
# -----------------------------------------------------------------------------


async def fetch_latest_commit_sha(
    access_token: str,
    owner: str,
    repo: str,
    branch: str = "main",
) -> str:
    """
    Fetch the latest commit SHA for the given branch from GitHub.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 401:
            security_logger.warning(
                "security_event=github_token_unauthorized owner=%s repo=%s", owner, repo
            )
            raise PermissionError("GitHub credentials are invalid or revoked")
        if res.status_code == 404:
            raise LookupError(f"Branch '{branch}' or repository '{owner}/{repo}' not found")
        if res.status_code != 200:
            raise RuntimeError(f"GitHub API error: status {res.status_code}")

        data = res.json()
        sha = data.get("sha")
        if not sha:
            raise ValueError("No commit SHA returned from GitHub")
        return str(sha)


async def fetch_repository_tree(
    access_token: str,
    owner: str,
    repo: str,
    commit_sha: str,
) -> list[dict[str, Any]]:
    """
    Fetch recursive git tree for the given commit SHA.
    Returns list of items with path, mode, type, sha, size.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 401:
            raise PermissionError("GitHub credentials are invalid or revoked")
        if res.status_code == 404:
            raise LookupError(f"Tree for commit {commit_sha} not found in {owner}/{repo}")
        if res.status_code != 200:
            raise RuntimeError(f"GitHub API error fetching tree: status {res.status_code}")

        data = res.json()
        tree = data.get("tree", [])
        if isinstance(tree, list):
            return [dict(item) for item in tree if isinstance(item, dict)]
        return []


async def fetch_blob_content(
    access_token: str,
    owner: str,
    repo: str,
    blob_sha: str,
) -> bytes:
    """
    Fetch file blob content from GitHub API.
    Returns raw bytes.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 401:
            raise PermissionError("GitHub credentials are invalid or revoked")
        if res.status_code != 200:
            raise RuntimeError(f"Failed to fetch blob {blob_sha}: status {res.status_code}")

        data = res.json()
        content_b64 = data.get("content", "")
        encoding = data.get("encoding", "base64")
        if encoding == "base64":
            # GitHub may include newlines in base64 string
            clean_b64 = content_b64.replace("\n", "").replace("\r", "")
            return bytes(base64.b64decode(clean_b64))
        return str(content_b64).encode("utf-8")
