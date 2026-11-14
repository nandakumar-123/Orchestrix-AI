import os

# -----------------------------------------------------------------------------
# Known Framework Detection Rules based on file existence and dependency names
# -----------------------------------------------------------------------------

# Framework detection based on file signatures in repo
FRAMEWORK_FILE_SIGNATURES: dict[str, list[str]] = {
    "Next.js": ["next.config.js", "next.config.mjs", "next.config.ts"],
    "Angular": ["angular.json"],
    "Vue": ["vue.config.js", "vue.config.ts", "vite.config.js", "vite.config.ts"],
    "Svelte": ["svelte.config.js", "svelte.config.ts"],
    "Django": ["manage.py"],
    "Flask": ["wsgi.py"],
    "Spring Boot": [
        "src/main/resources/application.properties",
        "src/main/resources/application.yml",
    ],
    "ASP.NET": ["Program.cs", "Startup.cs"],
    "Laravel": ["artisan"],
    "Rails": ["bin/rails", "config/routes.rb"],
    "Flutter": ["pubspec.yaml"],
    "Android": ["AndroidManifest.xml", "build.gradle", "build.gradle.kts"],
    "iOS": ["Podfile", "Package.swift"],
}

# Framework detection based on declared package dependencies
FRAMEWORK_DEP_SIGNATURES: dict[str, set[str]] = {
    "React": {"react", "react-dom"},
    "Next.js": {"next"},
    "Angular": {"@angular/core"},
    "Vue": {"vue", "nuxt"},
    "Svelte": {"svelte", "@sveltejs/kit"},
    "Django": {"django"},
    "Flask": {"flask"},
    "FastAPI": {"fastapi"},
    "Spring Boot": {"org.springframework.boot", "spring-boot"},
    "ASP.NET": {"Microsoft.AspNetCore", "Microsoft.NET.Sdk.Web"},
    "Laravel": {"laravel/framework"},
    "Rails": {"rails"},
    "Flutter": {"flutter"},
}


def detect_frameworks(
    file_paths: list[str],
    declared_dependencies: list[str] | set[str] | None = None,
) -> list[str]:
    """
    Detect software frameworks used by repository without executing any project code.
    Matches declared dependencies and key configuration files.
    """
    detected: set[str] = set()
    paths_set = {p.replace("\\", "/") for p in file_paths}
    basenames_set = {os.path.basename(p).lower() for p in file_paths}
    deps_set = {d.lower() for d in (declared_dependencies or [])}

    # 1. Check file signatures
    for fw, files in FRAMEWORK_FILE_SIGNATURES.items():
        for f in files:
            f_lower = f.lower()
            if "/" in f_lower:
                if any(p.lower().endswith(f_lower) for p in paths_set):
                    detected.add(fw)
                    break
            else:
                if f_lower in basenames_set:
                    # Guardrails for common names
                    if fw == "Django" and "manage.py" in basenames_set:
                        detected.add("Django")
                    elif fw == "Laravel" and "artisan" in basenames_set:
                        detected.add("Laravel")
                    elif fw == "Rails" and any("routes.rb" in p for p in paths_set):
                        detected.add("Rails")
                    elif fw == "Next.js" and any("next.config" in b for b in basenames_set):
                        detected.add("Next.js")
                    elif fw == "Angular" and "angular.json" in basenames_set:
                        detected.add("Angular")
                    elif fw == "Svelte" and any("svelte.config" in b for b in basenames_set):
                        detected.add("Svelte")

    # 2. Check dependency signatures
    for fw, dep_names in FRAMEWORK_DEP_SIGNATURES.items():
        if any(d.lower() in deps_set for d in dep_names):
            detected.add(fw)

    # 3. Dedicated check for FastAPI and Flask from files / imports
    if "FastAPI" not in detected:
        if any(d == "fastapi" for d in deps_set):
            detected.add("FastAPI")

    return sorted(detected)
