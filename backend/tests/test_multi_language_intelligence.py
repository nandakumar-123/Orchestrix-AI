from app.services.code_intelligence import PARSER_REGISTRY, analyze_code_content
from app.services.dependency_intelligence import (
    parse_build_sbt,
    parse_composer_json,
    parse_csproj,
    parse_gemfile,
    parse_julia_project_toml,
    parse_mix_exs,
    parse_package_swift,
    parse_pom_xml,
    parse_pubspec_yaml,
    parse_r_description,
)
from app.services.framework_detection import detect_frameworks
from app.services.repository_ingestion import detect_language

# -----------------------------------------------------------------------------
# 1. Multi-Language Registry & Parser Initialization Tests
# -----------------------------------------------------------------------------


def test_parser_registry_contains_over_35_languages() -> None:
    langs = PARSER_REGISTRY.get_supported_languages()
    assert len(langs) >= 35
    expected_sample = [
        "Python",
        "JavaScript",
        "TypeScript",
        "Java",
        "C",
        "C++",
        "PHP",
        "C#",
        "Go",
        "Rust",
        "Ruby",
        "Swift",
        "Kotlin",
        "Dart",
        "HTML",
        "CSS",
        "SQL",
        "Svelte",
        "YAML",
        "XML",
        "JSON",
        "Bash",
        "PowerShell",
        "Lua",
        "Scala",
        "Elixir",
        "Haskell",
        "Perl",
        "Objective-C",
        "OCaml",
        "Julia",
        "Zig",
        "Solidity",
        "Groovy",
        "Fortran",
        "Pascal",
    ]
    for lang in expected_sample:
        assert lang in langs, f"Expected {lang} in supported languages"


# -----------------------------------------------------------------------------
# 2. Individual Language AST Parsing & Symbol Extraction Tests
# -----------------------------------------------------------------------------


def test_go_ast_extraction() -> None:
    code = b"""package main
import "fmt"
type Worker struct {
    ID int
}
func (w *Worker) Process() error {
    return nil
}
func main() {
    fmt.Println("ok")
}
"""
    intel = analyze_code_content(code, "Go")
    assert intel.line_count > 0
    assert len(intel.symbols) >= 3
    names = [s.name for s in intel.symbols]
    assert "Worker" in names
    assert "Process" in names
    assert "main" in names
    assert any(i.module_name == "fmt" for i in intel.imports)


def test_rust_ast_extraction() -> None:
    code = b"""use std::collections::HashMap;
pub struct Cache {
    data: HashMap<String, String>,
}
impl Cache {
    pub fn new() -> Self {
        Cache { data: HashMap::new() }
    }
}
pub fn run() {}
"""
    intel = analyze_code_content(code, "Rust")
    names = [s.name for s in intel.symbols]
    assert "Cache" in names
    assert "new" in names
    assert "run" in names
    assert any("std::collections::HashMap" in i.module_name for i in intel.imports)


def test_c_sharp_ast_extraction() -> None:
    code = b"""using System;
namespace Orchestrix.Services {
    public interface IEngine {
        void Execute();
    }
    public class Engine : IEngine {
        public void Execute() {}
    }
}
"""
    intel = analyze_code_content(code, "C#")
    names = [s.name for s in intel.symbols]
    assert "IEngine" in names
    assert "Engine" in names
    assert "Execute" in names
    assert any(i.module_name == "System" for i in intel.imports)


def test_php_ast_extraction() -> None:
    code = b"""<?php
namespace App\\Http;
use App\\Models\User;
class UserController {
    public function show($id) {
        return User::find($id);
    }
}
function helper() {}
"""
    intel = analyze_code_content(code, "PHP")
    names = [s.name for s in intel.symbols]
    assert "UserController" in names
    assert "show" in names
    assert "helper" in names
    assert any("App\\Models\\User" in i.module_name for i in intel.imports)


def test_ruby_ast_extraction() -> None:
    code = b"""require "json"
module Core
  class Processor
    def perform
    end
  end
end
def top_level
end
"""
    intel = analyze_code_content(code, "Ruby")
    names = [s.name for s in intel.symbols]
    assert "Core" in names
    assert "Processor" in names
    assert "perform" in names
    assert "top_level" in names
    assert any("json" in i.module_name for i in intel.imports)


def test_swift_ast_extraction() -> None:
    code = b"""import Foundation
protocol Disconnectable {
    func disconnect()
}
class NetworkService: Disconnectable {
    func disconnect() {}
}
func setup() {}
"""
    intel = analyze_code_content(code, "Swift")
    names = [s.name for s in intel.symbols]
    assert "Disconnectable" in names
    assert "NetworkService" in names
    assert "disconnect" in names
    assert "setup" in names
    assert any(i.module_name == "Foundation" for i in intel.imports)


def test_kotlin_ast_extraction() -> None:
    code = b"""package com.orchestrix
import java.util.UUID
interface Identifiable {
    fun getId(): UUID
}
class Account(val id: UUID) : Identifiable {
    override fun getId(): UUID = id
}
fun createAccount(): Account = Account(UUID.randomUUID())
"""
    intel = analyze_code_content(code, "Kotlin")
    names = [s.name for s in intel.symbols]
    assert "Identifiable" in names
    assert "Account" in names
    assert "createAccount" in names
    assert any("java.util.UUID" in i.module_name for i in intel.imports)


def test_dart_ast_extraction() -> None:
    code = b"""import 'dart:async';
class DataStreamer {
    void stream() {}
}
void main() {}
"""
    intel = analyze_code_content(code, "Dart")
    names = [s.name for s in intel.symbols]
    assert "DataStreamer" in names or "main" in names
    assert any("dart:async" in i.module_name for i in intel.imports)


def test_bash_and_powershell_ast_extraction() -> None:
    bash_code = b"""#!/bin/bash
function deploy_service() {
    echo "deploying"
}
cleanup_cache() {
    rm -rf /tmp/cache
}
"""
    sh_intel = analyze_code_content(bash_code, "Bash")
    sh_names = [s.name for s in sh_intel.symbols]
    assert "deploy_service" in sh_names or "cleanup_cache" in sh_names

    ps_code = b"""function Get-ServiceHealth {
    param($ServiceName)
    Write-Output "healthy"
}
function Start-AgentService {
}
"""
    ps_intel = analyze_code_content(ps_code, "PowerShell")
    ps_names = [s.name for s in ps_intel.symbols]
    assert "Get-ServiceHealth" in ps_names or "Start-AgentService" in ps_names


def test_lua_scala_elixir_haskell_extraction() -> None:
    # Lua
    lua_code = b"""local http = require("socket.http")
function fetch_data(url)
    return http.request(url)
end
"""
    l_intel = analyze_code_content(lua_code, "Lua")
    assert any(s.name == "fetch_data" for s in l_intel.symbols)

    # Scala
    scala_code = b"""package com.worker
import scala.concurrent.Future
class TaskExecutor {
    def execute(): Unit = {}
}
"""
    sc_intel = analyze_code_content(scala_code, "Scala")
    assert any(s.name == "TaskExecutor" for s in sc_intel.symbols)

    # Elixir
    ex_code = b"""defmodule Orchestrix.Worker do
  def perform_job(args) do
    {:ok, args}
  end
end
"""
    ex_intel = analyze_code_content(ex_code, "Elixir")
    assert len(ex_intel.symbols) >= 1

    # Haskell
    hs_code = b"""module Solver where
import Data.Maybe
calculateSum :: Int -> Int -> Int
calculateSum x y = x + y
"""
    hs_intel = analyze_code_content(hs_code, "Haskell")
    assert len(hs_intel.imports) >= 1


def test_solidity_and_julia_and_zig_extraction() -> None:
    # Solidity
    sol_code = b"""pragma solidity ^0.8.20;
import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
contract GovernanceToken is ERC20 {
    function mint(address to, uint256 amount) public {}
}
"""
    sol_intel = analyze_code_content(sol_code, "Solidity")
    assert any(s.name == "GovernanceToken" for s in sol_intel.symbols)

    # Julia
    jl_code = b"""using DataFrames
struct Point
    x::Float64
    y::Float64
end
function compute_distance(p1, p2)
    return sqrt((p1.x - p2.x)^2 + (p1.y - p2.y)^2)
end
"""
    jl_intel = analyze_code_content(jl_code, "Julia")
    assert any(s.name in ("Point", "compute_distance") for s in jl_intel.symbols)

    # Zig
    zig_code = b"""const std = @import("std");
pub fn calculateHash() u32 {
    return 42;
}
"""
    zig_intel = analyze_code_content(zig_code, "Zig")
    assert any(s.name == "calculateHash" for s in zig_intel.symbols)


# -----------------------------------------------------------------------------
# 3. Language & Shebang Detection Tests
# -----------------------------------------------------------------------------


def test_language_detection_extended() -> None:
    assert detect_language("script.php") == "PHP"
    assert detect_language("Service.cs") == "C#"
    assert detect_language("main.go") == "Go"
    assert detect_language("lib.rs") == "Rust"
    assert detect_language("app.rb") == "Ruby"
    assert detect_language("View.swift") == "Swift"
    assert detect_language("App.kt") == "Kotlin"
    assert detect_language("main.dart") == "Dart"
    assert detect_language("deploy.sh") == "Bash"
    assert detect_language("script.ps1") == "PowerShell"
    assert detect_language("init.lua") == "Lua"
    assert detect_language("App.scala") == "Scala"
    assert detect_language("app.ex") == "Elixir"
    assert detect_language("Main.hs") == "Haskell"
    assert detect_language("script.pl") == "Perl"
    assert detect_language("contract.sol") == "Solidity"
    assert detect_language("model.jl") == "Julia"
    assert detect_language("main.zig") == "Zig"
    assert detect_language("math.f90") == "Fortran"
    assert detect_language("App.vue") is None  # fallback for unregistered
    assert detect_language("Dockerfile") == "Dockerfile"
    assert detect_language("Makefile") == "Make"
    assert detect_language("CMakeLists.txt") == "CMake"

    # Shebang detection
    assert detect_language("bin/tool", first_line="#!/usr/bin/env python3") == "Python"
    assert detect_language("bin/run", first_line="#!/bin/bash") == "Bash"
    assert detect_language("bin/exec", first_line="#!/usr/bin/ruby") == "Ruby"


# -----------------------------------------------------------------------------
# 4. Dependency Manifest Parsing Tests
# -----------------------------------------------------------------------------


def test_extended_manifest_parsing() -> None:
    # 1. PHP composer.json
    composer = '{"require": {"php": "^8.2", "laravel/framework": "^10.0"}, "require-dev": {"phpunit/phpunit": "^10.0"}}'
    php_deps = parse_composer_json(composer)
    assert len(php_deps) == 2
    assert any(d.name == "laravel/framework" and d.package_manager == "composer" for d in php_deps)
    assert any(
        d.name == "phpunit/phpunit" and d.dependency_type == "dev_dependency" for d in php_deps
    )

    # 2. C# .csproj
    csproj = """<Project Sdk="Microsoft.NET.Sdk">
  <ItemGroup>
    <PackageReference Include="Microsoft.AspNetCore.OpenApi" Version="8.0.0" />
    <PackageReference Include="Swashbuckle.AspNetCore" Version="6.5.0" />
  </ItemGroup>
</Project>"""
    cs_deps = parse_csproj(csproj)
    assert len(cs_deps) == 2
    assert cs_deps[0].name == "Microsoft.AspNetCore.OpenApi"
    assert cs_deps[0].package_manager == "nuget"

    # 3. Ruby Gemfile
    gemfile = """source "https://rubygems.org"
gem "rails", "~> 7.1.0"
gem "pg", ">= 1.5.0"
"""
    rb_deps = parse_gemfile(gemfile)
    assert len(rb_deps) == 2
    assert rb_deps[0].name == "rails"
    assert rb_deps[0].package_manager == "gem"

    # 4. Swift Package.swift
    pkg_swift = """// swift-tools-version:5.7
import PackageDescription
let package = Package(
    dependencies: [
        .package(url: "https://github.com/apple/swift-argument-parser", from: "1.2.0"),
    ]
)"""
    swift_deps = parse_package_swift(pkg_swift)
    assert len(swift_deps) == 1
    assert swift_deps[0].name == "swift-argument-parser"
    assert swift_deps[0].package_manager == "swift"

    # 5. Maven pom.xml
    pom = """<project>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
      <version>3.2.0</version>
    </dependency>
  </dependencies>
</project>"""
    maven_deps = parse_pom_xml(pom)
    assert len(maven_deps) == 1
    assert maven_deps[0].name == "org.springframework.boot:spring-boot-starter-web"
    assert maven_deps[0].package_manager == "maven"

    # 6. Dart pubspec.yaml
    pubspec = """name: my_app
dependencies:
  flutter:
    sdk: flutter
  http: ^1.1.0
dev_dependencies:
  flutter_test:
    sdk: flutter
  mocktail: ^1.0.0
"""
    dart_deps = parse_pubspec_yaml(pubspec)
    assert len(dart_deps) == 2
    assert any(d.name == "http" and d.package_manager == "pub" for d in dart_deps)

    # 7. Elixir mix.exs
    mix = """defmodule App.MixProject do
  defp deps do
    [
      {:phoenix, "~> 1.7.10"},
      {:jason, "~> 1.4"}
    ]
  end
end"""
    mix_deps = parse_mix_exs(mix)
    assert len(mix_deps) == 2
    assert mix_deps[0].name == "phoenix"
    assert mix_deps[0].package_manager == "hex"

    # 8. Scala build.sbt
    sbt = """libraryDependencies ++= Seq(
  "org.typelevel" %% "cats-core" % "2.10.0",
  "org.scalatest" %% "scalatest" % "3.2.17" % Test
)"""
    sbt_deps = parse_build_sbt(sbt)
    assert len(sbt_deps) == 2
    assert sbt_deps[0].name == "org.typelevel:cats-core"
    assert sbt_deps[1].dependency_type == "dev_dependency"

    # 9. R DESCRIPTION
    desc = """Package: MyPkg
Imports:
    ggplot2 (>= 3.4.0),
    dplyr
Suggests:
    testthat
"""
    r_deps = parse_r_description(desc)
    assert len(r_deps) == 3
    assert any(d.name == "ggplot2" for d in r_deps)
    assert any(d.name == "testthat" and d.dependency_type == "dev_dependency" for d in r_deps)

    # 10. Julia Project.toml
    julia_toml = """[deps]
DataFrames = "a93c0a0c-e570-568a-b307-d41981ab1242"
CSV = "336ed68f-0bac-5ca0-87d4-7b16caf5d00b"
[compat]
DataFrames = "1.6"
"""
    jl_deps = parse_julia_project_toml(julia_toml)
    assert len(jl_deps) == 2
    assert any(d.name == "DataFrames" and d.version_spec == "1.6" for d in jl_deps)


# -----------------------------------------------------------------------------
# 5. Framework Detection Tests
# -----------------------------------------------------------------------------


def test_framework_detection() -> None:
    # Next.js & React
    next_fw = detect_frameworks(
        file_paths=["next.config.js", "pages/index.tsx"],
        declared_dependencies=["next", "react", "react-dom"],
    )
    assert "Next.js" in next_fw
    assert "React" in next_fw

    # Django
    django_fw = detect_frameworks(
        file_paths=["manage.py", "core/settings.py"],
        declared_dependencies=["django", "psycopg2"],
    )
    assert "Django" in django_fw

    # Laravel
    laravel_fw = detect_frameworks(
        file_paths=["artisan", "composer.json"],
        declared_dependencies=["laravel/framework"],
    )
    assert "Laravel" in laravel_fw

    # Flutter
    flutter_fw = detect_frameworks(
        file_paths=["pubspec.yaml", "lib/main.dart"],
        declared_dependencies=["flutter"],
    )
    assert "Flutter" in flutter_fw

    # Spring Boot
    spring_fw = detect_frameworks(
        file_paths=["pom.xml", "src/main/resources/application.properties"],
        declared_dependencies=["org.springframework.boot:spring-boot-starter-web"],
    )
    assert "Spring Boot" in spring_fw
