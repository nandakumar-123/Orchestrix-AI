import json
import logging
import os
import re
import tomllib
from dataclasses import dataclass

logger = logging.getLogger("orchestrix.dependencies")


@dataclass
class ManifestDependency:
    name: str
    version_spec: str | None
    dependency_type: str  # "package_dependency", "dev_dependency"
    package_manager: str  # "npm", "pip", "cargo", "go"


def parse_package_json(content: str) -> list[ManifestDependency]:
    """Parse Node.js package.json manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = json.loads(content)
        # Production dependencies
        for pkg, ver in data.get("dependencies", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="package_dependency",
                    package_manager="npm",
                )
            )
        # Dev dependencies
        for pkg, ver in data.get("devDependencies", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="dev_dependency",
                    package_manager="npm",
                )
            )
        # Peer dependencies
        for pkg, ver in data.get("peerDependencies", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="peer_dependency",
                    package_manager="npm",
                )
            )
    except Exception as exc:
        logger.warning("Error parsing package.json: %s", exc)
    return deps


def _split_python_pkg(spec_line: str) -> tuple[str, str | None]:
    """Split python package name from operators like >=, ==, <, ~, etc."""
    clean = spec_line.split("#")[0].strip()
    match = re.match(r"^([a-zA-Z0-9_\-\.]+)(.*)$", clean)
    if not match:
        return clean, None
    name = match.group(1).strip()
    ver = match.group(2).strip() or None
    return name, ver


def parse_pyproject_toml(content: str) -> list[ManifestDependency]:
    """Parse Python pyproject.toml manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = tomllib.loads(content)
        # 1. PEP 621: [project.dependencies]
        project = data.get("project", {})
        for spec in project.get("dependencies", []):
            name, ver = _split_python_pkg(spec)
            deps.append(
                ManifestDependency(
                    name=name,
                    version_spec=ver,
                    dependency_type="package_dependency",
                    package_manager="pip",
                )
            )

        # 2. PEP 621: [project.optional-dependencies]
        for _opt_group, specs in project.get("optional-dependencies", {}).items():
            for spec in specs:
                name, ver = _split_python_pkg(spec)
                deps.append(
                    ManifestDependency(
                        name=name,
                        version_spec=ver,
                        dependency_type="dev_dependency",
                        package_manager="pip",
                    )
                )

        # 3. Poetry: [tool.poetry.dependencies]
        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        for pkg, ver in poetry_deps.items():
            if pkg.lower() != "python":
                ver_str = (
                    ver
                    if isinstance(ver, str)
                    else ver.get("version", None)
                    if isinstance(ver, dict)
                    else None
                )
                deps.append(
                    ManifestDependency(
                        name=pkg,
                        version_spec=str(ver_str) if ver_str else None,
                        dependency_type="package_dependency",
                        package_manager="pip",
                    )
                )

        # 4. Dependency groups (uv / poetry 1.2+): [dependency-groups]
        dep_groups = data.get("dependency-groups", {})
        for _group_name, specs in dep_groups.items():
            for spec in specs:
                if isinstance(spec, str):
                    name, ver = _split_python_pkg(spec)
                    deps.append(
                        ManifestDependency(
                            name=name,
                            version_spec=ver,
                            dependency_type="dev_dependency",
                            package_manager="pip",
                        )
                    )
    except Exception as exc:
        logger.warning("Error parsing pyproject.toml: %s", exc)
    return deps


def parse_requirements_txt(content: str) -> list[ManifestDependency]:
    """Parse Python requirements.txt manifest."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name, ver = _split_python_pkg(line)
        if name:
            deps.append(
                ManifestDependency(
                    name=name,
                    version_spec=ver,
                    dependency_type="package_dependency",
                    package_manager="pip",
                )
            )
    return deps


def parse_cargo_toml(content: str) -> list[ManifestDependency]:
    """Parse Rust Cargo.toml manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = tomllib.loads(content)
        # Production dependencies
        for pkg, val in data.get("dependencies", {}).items():
            ver = (
                val
                if isinstance(val, str)
                else val.get("version")
                if isinstance(val, dict)
                else None
            )
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver) if ver else None,
                    dependency_type="package_dependency",
                    package_manager="cargo",
                )
            )
        # Dev dependencies
        for pkg, val in data.get("dev-dependencies", {}).items():
            ver = (
                val
                if isinstance(val, str)
                else val.get("version")
                if isinstance(val, dict)
                else None
            )
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver) if ver else None,
                    dependency_type="dev_dependency",
                    package_manager="cargo",
                )
            )
    except Exception as exc:
        logger.warning("Error parsing Cargo.toml: %s", exc)
    return deps


def parse_go_mod(content: str) -> list[ManifestDependency]:
    """Parse Go go.mod manifest."""
    deps: list[ManifestDependency] = []
    in_require_block = False
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("require ("):
            in_require_block = True
            continue
        if in_require_block and line == ")":
            in_require_block = False
            continue

        if in_require_block:
            parts = line.split()
            if len(parts) >= 2:
                deps.append(
                    ManifestDependency(
                        name=parts[0],
                        version_spec=parts[1],
                        dependency_type="package_dependency",
                        package_manager="go",
                    )
                )
        elif line.startswith("require "):
            parts = line.replace("require ", "").strip().split()
            if len(parts) >= 2:
                deps.append(
                    ManifestDependency(
                        name=parts[0],
                        version_spec=parts[1],
                        dependency_type="package_dependency",
                        package_manager="go",
                    )
                )
    return deps


def parse_dependency_manifest(path: str, content: str) -> list[ManifestDependency]:
    """Dispatch manifest parsing according to filename."""
    filename = os.path.basename(path).lower()
    if filename == "package.json":
        return parse_package_json(content)
    if filename == "pyproject.toml":
        return parse_pyproject_toml(content)
    if filename in ("requirements.txt", "requirements-dev.txt", "requirements_dev.txt"):
        return parse_requirements_txt(content)
    if filename == "cargo.toml":
        return parse_cargo_toml(content)
    if filename == "go.mod":
        return parse_go_mod(content)
    return []
