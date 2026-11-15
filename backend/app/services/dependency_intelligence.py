import json
import logging
import os
import re
import tomllib
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import yaml  # type: ignore[import-untyped]

logger = logging.getLogger("orchestrix.dependencies")


@dataclass
class ManifestDependency:
    name: str
    version_spec: str | None
    dependency_type: str  # "package_dependency", "dev_dependency", "peer_dependency"
    package_manager: str  # "npm", "pip", "cargo", "go", "composer", "nuget", "gem", "swift", "gradle", "maven", "pub", "hex", "sbt", "cran", "julia"


# -----------------------------------------------------------------------------
# Node.js: package.json
# -----------------------------------------------------------------------------


def parse_package_json(content: str) -> list[ManifestDependency]:
    """Parse Node.js package.json manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = json.loads(content)
        for pkg, ver in data.get("dependencies", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="package_dependency",
                    package_manager="npm",
                )
            )
        for pkg, ver in data.get("devDependencies", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="dev_dependency",
                    package_manager="npm",
                )
            )
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


# -----------------------------------------------------------------------------
# Python: pyproject.toml & requirements.txt
# -----------------------------------------------------------------------------


def _split_python_pkg(spec_line: str) -> tuple[str, str | None]:
    """Split python package name from operators like >=, ==, <, ~, etc."""
    spec_clean = spec_line.strip().split(";")[0].strip()
    match = re.match(r"^([A-Za-z0-9_\-\.]+)\s*([><=~!].*)?$", spec_clean)
    if match:
        name = match.group(1).strip()
        version = match.group(2).strip() if match.group(2) else None
        return name, version
    return spec_clean, None


def parse_pyproject_toml(content: str) -> list[ManifestDependency]:
    """Parse Python pyproject.toml manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = tomllib.loads(content)
        project_deps = data.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            for dep_str in project_deps:
                name, ver = _split_python_pkg(dep_str)
                if name:
                    deps.append(
                        ManifestDependency(
                            name=name,
                            version_spec=ver,
                            dependency_type="package_dependency",
                            package_manager="pip",
                        )
                    )

        opt_deps = data.get("project", {}).get("optional-dependencies", {})
        if isinstance(opt_deps, dict):
            for group_name, group_list in opt_deps.items():
                if isinstance(group_list, list):
                    for dep_str in group_list:
                        name, ver = _split_python_pkg(dep_str)
                        if name:
                            deps.append(
                                ManifestDependency(
                                    name=name,
                                    version_spec=ver,
                                    dependency_type=f"optional:{group_name}",
                                    package_manager="pip",
                                )
                            )

        # PEP 735 dependency-groups
        dep_groups = data.get("dependency-groups", {})
        if isinstance(dep_groups, dict):
            for group_name, group_list in dep_groups.items():
                if isinstance(group_list, list):
                    for dep_str in group_list:
                        name, ver = _split_python_pkg(dep_str)
                        if name:
                            deps.append(
                                ManifestDependency(
                                    name=name,
                                    version_spec=ver,
                                    dependency_type="dev_dependency"
                                    if group_name.lower() in ("dev", "test")
                                    else f"group:{group_name}",
                                    package_manager="pip",
                                )
                            )

        poetry_deps = data.get("tool", {}).get("poetry", {}).get("dependencies", {})
        if isinstance(poetry_deps, dict):
            for pkg, ver_spec in poetry_deps.items():
                if pkg.lower() == "python":
                    continue
                v_str = ver_spec if isinstance(ver_spec, str) else str(ver_spec.get("version", ""))
                deps.append(
                    ManifestDependency(
                        name=pkg,
                        version_spec=v_str or None,
                        dependency_type="package_dependency",
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
        if not line or line.startswith("#") or line.startswith("-r ") or line.startswith("-i "):
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


# -----------------------------------------------------------------------------
# Rust: Cargo.toml
# -----------------------------------------------------------------------------


def parse_cargo_toml(content: str) -> list[ManifestDependency]:
    """Parse Rust Cargo.toml manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = tomllib.loads(content)
        prod = data.get("dependencies", {})
        for pkg, spec in prod.items():
            ver = (
                spec
                if isinstance(spec, str)
                else spec.get("version")
                if isinstance(spec, dict)
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
        dev = data.get("dev-dependencies", {})
        for pkg, spec in dev.items():
            ver = (
                spec
                if isinstance(spec, str)
                else spec.get("version")
                if isinstance(spec, dict)
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


# -----------------------------------------------------------------------------
# Go: go.mod
# -----------------------------------------------------------------------------


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


# -----------------------------------------------------------------------------
# PHP: composer.json
# -----------------------------------------------------------------------------


def parse_composer_json(content: str) -> list[ManifestDependency]:
    """Parse PHP composer.json manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = json.loads(content)
        for pkg, ver in data.get("require", {}).items():
            if pkg.lower() == "php":
                continue
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="package_dependency",
                    package_manager="composer",
                )
            )
        for pkg, ver in data.get("require-dev", {}).items():
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver),
                    dependency_type="dev_dependency",
                    package_manager="composer",
                )
            )
    except Exception as exc:
        logger.warning("Error parsing composer.json: %s", exc)
    return deps


# -----------------------------------------------------------------------------
# C#: .csproj and packages.config (XML)
# -----------------------------------------------------------------------------


def parse_csproj(content: str) -> list[ManifestDependency]:
    """Parse C# .csproj XML file for PackageReference elements."""
    deps: list[ManifestDependency] = []
    try:
        root = ET.fromstring(content)
        # Find all PackageReference nodes
        for elem in root.iter():
            if elem.tag.endswith("PackageReference"):
                include = elem.attrib.get("Include") or elem.attrib.get("Update")
                version = elem.attrib.get("Version")
                if not version:
                    # check child <Version> tag
                    for child in elem:
                        if child.tag.endswith("Version") and child.text:
                            version = child.text.strip()
                            break
                if include:
                    deps.append(
                        ManifestDependency(
                            name=include,
                            version_spec=version,
                            dependency_type="package_dependency",
                            package_manager="nuget",
                        )
                    )
    except Exception as exc:
        logger.warning("Error parsing .csproj: %s", exc)
    return deps


def parse_packages_config(content: str) -> list[ManifestDependency]:
    """Parse legacy C# packages.config XML."""
    deps: list[ManifestDependency] = []
    try:
        root = ET.fromstring(content)
        for elem in root.iter():
            if elem.tag.endswith("package"):
                pkg_id = elem.attrib.get("id")
                version = elem.attrib.get("version")
                is_dev = elem.attrib.get("developmentDependency", "false").lower() == "true"
                if pkg_id:
                    deps.append(
                        ManifestDependency(
                            name=pkg_id,
                            version_spec=version,
                            dependency_type="dev_dependency" if is_dev else "package_dependency",
                            package_manager="nuget",
                        )
                    )
    except Exception as exc:
        logger.warning("Error parsing packages.config: %s", exc)
    return deps


# -----------------------------------------------------------------------------
# Ruby: Gemfile
# -----------------------------------------------------------------------------


def parse_gemfile(content: str) -> list[ManifestDependency]:
    """Parse Ruby Gemfile."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # match: gem 'rails', '~> 7.0' or gem "puma"
        match = re.match(r"""^gem\s+['"]([^'"]+)['"](?:\s*,\s*['"]([^'"]+)['"])?""", line)
        if match:
            pkg = match.group(1)
            ver = match.group(2)
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=ver,
                    dependency_type="package_dependency",
                    package_manager="gem",
                )
            )
    return deps


# -----------------------------------------------------------------------------
# Swift: Package.swift
# -----------------------------------------------------------------------------


def parse_package_swift(content: str) -> list[ManifestDependency]:
    """Parse Swift Package.swift dependencies."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        # .package(url: "https://github.com/apple/swift-algorithms", from: "1.0.0")
        match = re.search(
            r"""\.package\s*\(\s*(?:url:\s*)?["']([^"']+)["'](?:\s*,\s*(?:exact|from):\s*["']([^"']+)["'])?""",
            line,
        )
        if match:
            url = match.group(1)
            ver = match.group(2)
            # extract repo name from URL
            name = url.rstrip("/").split("/")[-1]
            if name.endswith(".git"):
                name = name[:-4]
            deps.append(
                ManifestDependency(
                    name=name,
                    version_spec=ver,
                    dependency_type="package_dependency",
                    package_manager="swift",
                )
            )
    return deps


# -----------------------------------------------------------------------------
# Java/Kotlin: Maven pom.xml & Gradle
# -----------------------------------------------------------------------------


def parse_pom_xml(content: str) -> list[ManifestDependency]:
    """Parse Maven pom.xml dependencies."""
    deps: list[ManifestDependency] = []
    try:
        root = ET.fromstring(content)
        for dep in root.iter():
            if dep.tag.endswith("dependency"):
                group_id = ""
                artifact_id = ""
                version = ""
                scope = "compile"
                for child in dep:
                    tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    text = child.text.strip() if child.text else ""
                    if tag == "groupId":
                        group_id = text
                    elif tag == "artifactId":
                        artifact_id = text
                    elif tag == "version":
                        version = text
                    elif tag == "scope":
                        scope = text
                if artifact_id:
                    name = f"{group_id}:{artifact_id}" if group_id else artifact_id
                    is_dev = scope.lower() in ("test", "provided")
                    deps.append(
                        ManifestDependency(
                            name=name,
                            version_spec=version or None,
                            dependency_type="dev_dependency" if is_dev else "package_dependency",
                            package_manager="maven",
                        )
                    )
    except Exception as exc:
        logger.warning("Error parsing pom.xml: %s", exc)
    return deps


def parse_build_gradle(content: str) -> list[ManifestDependency]:
    """Parse Gradle build.gradle / build.gradle.kts dependencies."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        # implementation("org.springframework.boot:spring-boot-starter:3.0.0")
        # testImplementation 'junit:junit:4.13'
        match = re.search(
            r"""(?:implementation|api|compileOnly|runtimeOnly|testImplementation)\s*\(?\s*['"]([^'"]+)['"]\s*\)?""",
            line,
        )
        if match:
            spec = match.group(1)
            parts = spec.split(":")
            if len(parts) >= 2:
                name = f"{parts[0]}:{parts[1]}"
                ver = parts[2] if len(parts) >= 3 else None
                is_dev = "test" in line.lower()
                deps.append(
                    ManifestDependency(
                        name=name,
                        version_spec=ver,
                        dependency_type="dev_dependency" if is_dev else "package_dependency",
                        package_manager="gradle",
                    )
                )
    return deps


# -----------------------------------------------------------------------------
# Dart / Flutter: pubspec.yaml
# -----------------------------------------------------------------------------


def parse_pubspec_yaml(content: str) -> list[ManifestDependency]:
    """Parse Dart / Flutter pubspec.yaml."""
    deps: list[ManifestDependency] = []
    try:
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            for pkg, spec in (data.get("dependencies") or {}).items():
                if pkg.lower() == "flutter":
                    continue
                ver = (
                    spec
                    if isinstance(spec, str)
                    else spec.get("version")
                    if isinstance(spec, dict)
                    else None
                )
                deps.append(
                    ManifestDependency(
                        name=pkg,
                        version_spec=str(ver) if ver else None,
                        dependency_type="package_dependency",
                        package_manager="pub",
                    )
                )
            for pkg, spec in (data.get("dev_dependencies") or {}).items():
                if pkg.lower() in ("flutter_test", "flutter"):
                    continue
                ver = (
                    spec
                    if isinstance(spec, str)
                    else spec.get("version")
                    if isinstance(spec, dict)
                    else None
                )
                deps.append(
                    ManifestDependency(
                        name=pkg,
                        version_spec=str(ver) if ver else None,
                        dependency_type="dev_dependency",
                        package_manager="pub",
                    )
                )
    except Exception as exc:
        logger.warning("Error parsing pubspec.yaml: %s", exc)
    return deps


# -----------------------------------------------------------------------------
# Elixir: mix.exs
# -----------------------------------------------------------------------------


def parse_mix_exs(content: str) -> list[ManifestDependency]:
    """Parse Elixir mix.exs dependencies."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        # {:phoenix, "~> 1.7.0"}
        match = re.search(r"""\{:([A-Za-z0-9_]+)\s*,\s*["']([^"']+)["']""", line)
        if match:
            pkg = match.group(1)
            ver = match.group(2)
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=ver,
                    dependency_type="package_dependency",
                    package_manager="hex",
                )
            )
    return deps


# -----------------------------------------------------------------------------
# Scala: build.sbt
# -----------------------------------------------------------------------------


def parse_build_sbt(content: str) -> list[ManifestDependency]:
    """Parse Scala build.sbt dependencies."""
    deps: list[ManifestDependency] = []
    for line in content.splitlines():
        line = line.strip()
        # "org.scalatest" %% "scalatest" % "3.2.14" % Test
        match = re.search(
            r"""["']([^"']+)["']\s*%%?\s*["']([^"']+)["']\s*%\s*["']([^"']+)["']""", line
        )
        if match:
            group = match.group(1)
            artifact = match.group(2)
            ver = match.group(3)
            is_test = "% Test" in line or '% "test"' in line
            deps.append(
                ManifestDependency(
                    name=f"{group}:{artifact}",
                    version_spec=ver,
                    dependency_type="dev_dependency" if is_test else "package_dependency",
                    package_manager="sbt",
                )
            )
    return deps


# -----------------------------------------------------------------------------
# R: DESCRIPTION
# -----------------------------------------------------------------------------


def parse_r_description(content: str) -> list[ManifestDependency]:
    """Parse R package DESCRIPTION file."""
    deps: list[ManifestDependency] = []
    current_key = ""
    accum: dict[str, list[str]] = {"imports": [], "suggests": [], "depends": []}

    for line in content.splitlines():
        if line.startswith("Imports:"):
            current_key = "imports"
            accum["imports"].append(line.replace("Imports:", "").strip())
        elif line.startswith("Suggests:"):
            current_key = "suggests"
            accum["suggests"].append(line.replace("Suggests:", "").strip())
        elif line.startswith("Depends:"):
            current_key = "depends"
            accum["depends"].append(line.replace("Depends:", "").strip())
        elif line.startswith(" ") or line.startswith("\t"):
            if current_key in accum:
                accum[current_key].append(line.strip())
        else:
            current_key = ""

    for key, lines in accum.items():
        joined = " ".join(lines)
        for raw_item in joined.split(","):
            raw_item = raw_item.strip()
            if not raw_item or raw_item.lower() == "r":
                continue
            # e.g. ggplot2 (>= 3.0.0)
            m = re.match(r"^([A-Za-z0-9_\.]+)\s*(?:\((.*)\))?$", raw_item)
            if m:
                pkg = m.group(1)
                ver = m.group(2)
                deps.append(
                    ManifestDependency(
                        name=pkg,
                        version_spec=ver,
                        dependency_type="dev_dependency"
                        if key == "suggests"
                        else "package_dependency",
                        package_manager="cran",
                    )
                )
    return deps


# -----------------------------------------------------------------------------
# Julia: Project.toml
# -----------------------------------------------------------------------------


def parse_julia_project_toml(content: str) -> list[ManifestDependency]:
    """Parse Julia Project.toml manifest."""
    deps: list[ManifestDependency] = []
    try:
        data = tomllib.loads(content)
        deps_sec = data.get("deps", {})
        compat_sec = data.get("compat", {})
        for pkg in deps_sec.keys():
            ver = compat_sec.get(pkg)
            deps.append(
                ManifestDependency(
                    name=pkg,
                    version_spec=str(ver) if ver else None,
                    dependency_type="package_dependency",
                    package_manager="julia",
                )
            )
    except Exception as exc:
        logger.warning("Error parsing Julia Project.toml: %s", exc)
    return deps


# -----------------------------------------------------------------------------
# Unified Manifest Dispatcher
# -----------------------------------------------------------------------------


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
    if filename == "composer.json":
        return parse_composer_json(content)
    if filename.endswith(".csproj"):
        return parse_csproj(content)
    if filename == "packages.config":
        return parse_packages_config(content)
    if filename in ("gemfile", "gemfile.lock"):
        return parse_gemfile(content)
    if filename == "package.swift":
        return parse_package_swift(content)
    if filename == "pom.xml":
        return parse_pom_xml(content)
    if filename in ("build.gradle", "build.gradle.kts"):
        return parse_build_gradle(content)
    if filename == "pubspec.yaml":
        return parse_pubspec_yaml(content)
    if filename == "mix.exs":
        return parse_mix_exs(content)
    if filename == "build.sbt":
        return parse_build_sbt(content)
    if filename == "description":
        return parse_r_description(content)
    if filename == "project.toml":
        return parse_julia_project_toml(content)
    return []
