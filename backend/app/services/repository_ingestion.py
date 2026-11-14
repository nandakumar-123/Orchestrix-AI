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
    "vendor",
    "Pods",
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
    ".o",
    ".a",
    ".lib",
    ".pdb",
}

# Secret and Credential Patterns
SECRET_PATTERNS = [
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "credentials.json",
    "client_secret*.json",
    "*service-account*.json",
    "*.keystore",
    "*.jks",
]

# Mapping of file extensions to canonical language names (covering 40+ languages)
LANGUAGE_MAP: dict[str, str] = {
    # Core Languages
    ".py": "Python",
    ".pyw": "Python",
    ".js": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".jsx": "JSX",
    ".ts": "TypeScript",
    ".mts": "TypeScript",
    ".cts": "TypeScript",
    ".tsx": "TSX",
    ".java": "Java",
    ".c": "C",
    ".h": "C",
    ".cpp": "C++",
    ".cc": "C++",
    ".cxx": "C++",
    ".hpp": "C++",
    ".hh": "C++",
    ".hxx": "C++",
    # Group A
    ".php": "PHP",
    ".phtml": "PHP",
    ".cs": "C#",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".swift": "Swift",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".dart": "Dart",
    # Group B
    ".html": "HTML",
    ".htm": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".sass": "CSS",
    ".sql": "SQL",
    ".svelte": "Svelte",
    ".json": "JSON",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".xml": "XML",
    ".graphql": "GraphQL",
    ".gql": "GraphQL",
    # Group C
    ".sh": "Bash",
    ".bash": "Bash",
    ".zsh": "Bash",
    ".ps1": "PowerShell",
    ".psm1": "PowerShell",
    ".psd1": "PowerShell",
    ".lua": "Lua",
    ".r": "R",
    ".scala": "Scala",
    ".sc": "Scala",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".hs": "Haskell",
    ".lhs": "Haskell",
    ".pl": "Perl",
    ".pm": "Perl",
    # Group D
    ".m": "Objective-C",
    ".mm": "Objective-C",
    ".ml": "OCaml",
    ".mli": "OCaml",
    ".jl": "Julia",
    ".zig": "Zig",
    ".sol": "Solidity",
    ".groovy": "Groovy",
    ".gvy": "Groovy",
    ".f90": "Fortran",
    ".f95": "Fortran",
    ".f03": "Fortran",
    ".for": "Fortran",
    ".f": "Fortran",
    ".pas": "Pascal",
    ".pp": "Pascal",
    # Config / Build
    ".cmake": "CMake",
    ".toml": "TOML",
    ".md": "Markdown",
    ".markdown": "Markdown",
}

# Known Configuration & Manifest Filenames
SPECIAL_FILENAME_MAP: dict[str, str] = {
    "dockerfile": "Dockerfile",
    "containerfile": "Dockerfile",
    "makefile": "Make",
    "gnumakefile": "Make",
    "cmakelists.txt": "CMake",
    "gemfile": "Ruby",
    "rakefile": "Ruby",
    "package.json": "JSON",
    "composer.json": "JSON",
    "cargo.toml": "TOML",
    "pyproject.toml": "TOML",
    "go.mod": "Go",
    "pubspec.yaml": "YAML",
    "pom.xml": "XML",
}

MANIFEST_FILENAMES = {
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "cargo.toml",
    "go.mod",
    "composer.json",
    "packages.config",
    "gemfile",
    "package.swift",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "pubspec.yaml",
    "mix.exs",
    "build.sbt",
    "description",
    "project.toml",
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


def detect_language(path: str, first_line: str | None = None) -> str | None:
    """
    Detect programming language from file path, special filenames, or shebang lines.
    """
    basename = os.path.basename(path).lower()

    # 1. Check known special filenames
    if basename in SPECIAL_FILENAME_MAP:
        return SPECIAL_FILENAME_MAP[basename]
    if basename.startswith("dockerfile."):
        return "Dockerfile"
    if basename.endswith(".csproj"):
        return "C#"

    # 2. Check shebang if available
    if first_line and first_line.startswith("#!"):
        shebang = first_line.lower()
        if "python" in shebang:
            return "Python"
        if "node" in shebang or "deno" in shebang:
            return "JavaScript"
        if "bash" in shebang or "sh" in shebang:
            return "Bash"
        if "ruby" in shebang:
            return "Ruby"
        if "perl" in shebang:
            return "Perl"
        if "php" in shebang:
            return "PHP"
        if "lua" in shebang:
            return "Lua"
        if "julia" in shebang:
            return "Julia"

    # 3. Check extension
    _, ext = os.path.splitext(path)
    ext_lower = ext.lower()
    return LANGUAGE_MAP.get(ext_lower)


def is_manifest_file(path: str) -> bool:
    """Check if file is a recognized dependency manifest."""
    basename = os.path.basename(path).lower()
    if basename.endswith(".csproj"):
        return True
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
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            security_logger.error(
                "Failed to fetch commit SHA for %s/%s branch=%s: %d %s",
                owner,
                repo,
                branch,
                resp.status_code,
                resp.text,
            )
            raise RuntimeError(
                f"GitHub commit fetch failed ({resp.status_code}): {resp.json().get('message', 'Unknown error')}"
            )
        data = resp.json()
        return str(data.get("sha", ""))


async def fetch_repository_tree(
    access_token: str,
    owner: str,
    repo: str,
    commit_sha: str,
) -> list[dict[str, Any]]:
    """
    Fetch recursive git tree for a specific commit SHA using GitHub Git Trees API.
    GET /repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{commit_sha}?recursive=1"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            security_logger.error(
                "Failed to fetch Git tree for %s/%s sha=%s: %d",
                owner,
                repo,
                commit_sha,
                resp.status_code,
            )
            raise RuntimeError(
                f"GitHub tree fetch failed ({resp.status_code}): {resp.json().get('message', 'Unknown error')}"
            )
        data = resp.json()
        tree = data.get("tree", [])
        return list(tree)


async def fetch_blob_content(
    access_token: str,
    owner: str,
    repo: str,
    blob_sha: str,
) -> bytes:
    """
    Fetch blob contents from GitHub Git Blobs API.
    GET /repos/{owner}/{repo}/git/blobs/{blob_sha}
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/git/blobs/{blob_sha}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Orchestrix-AI",
    }

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise RuntimeError(f"Blob fetch failed ({resp.status_code})")
        data = resp.json()
        encoding = data.get("encoding", "")
        content_str = str(data.get("content", ""))
        if encoding == "base64":
            return base64.b64decode(content_str)
        return content_str.encode("utf-8")
