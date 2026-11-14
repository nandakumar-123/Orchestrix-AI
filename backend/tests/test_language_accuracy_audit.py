"""
PHASE 8.2 — MULTI-LANGUAGE PARSER ACCURACY AUDIT
Comprehensive test matrix testing all 40+ registered languages for AST extraction,
symbol accuracy, source locations, signatures, nested scopes, and edge cases.
"""

from typing import cast

import pytest

from app.services.code_intelligence import (
    PARSER_REGISTRY,
    analyze_code_content,
)

# -----------------------------------------------------------------------------
# 1. Complete Fixture Matrix for All 40+ Registered Languages
# -----------------------------------------------------------------------------

LANGUAGE_ACCURACY_FIXTURES: dict[str, dict[str, object]] = {
    "Python": {
        "code": b"""import os
from pathlib import Path

class Engine:
    def __init__(self, name: str):
        self.name = name

    def execute(self) -> bool:
        return True

async def start_server(port: int = 8080):
    pass
""",
        "expected_symbols": [
            ("Engine", "class", None),
            ("__init__", "method", "Engine"),
            ("execute", "method", "Engine"),
            ("start_server", "function", None),
        ],
        "expected_imports": ["os", "pathlib"],
    },
    "JavaScript": {
        "code": b"""const fs = require('fs');
import { debounce } from 'lodash';

class WorkerPool {
    constructor(size) {
        this.size = size;
    }
    dispatch(task) {
        return task();
    }
}

function processTask(id) {
    return id * 2;
}
""",
        "expected_symbols": [
            ("WorkerPool", "class", None),
            ("dispatch", "method", "WorkerPool"),
            ("processTask", "function", None),
        ],
        "expected_imports": ["fs", "lodash"],
    },
    "TypeScript": {
        "code": b"""import { EventEmitter } from 'events';

export interface ITaskRunner {
    run(taskName: string): Promise<void>;
}

export class TaskRunner implements ITaskRunner {
    async run(taskName: string): Promise<void> {
        console.log(taskName);
    }
}
""",
        "expected_symbols": [
            ("ITaskRunner", "interface", None),
            ("TaskRunner", "class", None),
            ("run", "method", "TaskRunner"),
        ],
        "expected_imports": ["events"],
    },
    "TSX": {
        "code": b"""import React from 'react';

export interface CardProps {
    title: string;
}

export function Card({ title }: CardProps) {
    return <div className="card">{title}</div>;
}
""",
        "expected_symbols": [
            ("CardProps", "interface", None),
            ("Card", "function", None),
        ],
        "expected_imports": ["react"],
    },
    "JSX": {
        "code": b"""import React from 'react';

export function Button({ label }) {
    return <button>{label}</button>;
}
""",
        "expected_symbols": [
            ("Button", "function", None),
        ],
        "expected_imports": ["react"],
    },
    "Java": {
        "code": b"""package com.orchestrix.core;

import java.util.Map;
import java.util.concurrent.Future;

public class ExecutionManager {
    private final String clusterId;

    public ExecutionManager(String clusterId) {
        this.clusterId = clusterId;
    }

    public Future<String> submitJob(String jobId) {
        return null;
    }
}

interface IHealthCheck {
    boolean isHealthy();
}
""",
        "expected_symbols": [
            ("ExecutionManager", "class", None),
            ("ExecutionManager", "method", "ExecutionManager"),
            ("submitJob", "method", "ExecutionManager"),
            ("IHealthCheck", "interface", None),
        ],
        "expected_imports": ["java.util.Map", "java.util.concurrent.Future"],
    },
    "C": {
        "code": b"""#include <stdio.h>
#include "engine.h"

struct Config {
    int max_workers;
    double timeout;
};

int initialize_system(struct Config *cfg) {
    return 0;
}
""",
        "expected_symbols": [
            ("Config", "struct", None),
            ("initialize_system", "function", None),
        ],
        "expected_imports": ["stdio.h", "engine.h"],
    },
    "C++": {
        "code": b"""#include <iostream>
#include <vector>

class ThreadPool {
public:
    ThreadPool(int threads);
    void enqueue_job(int job_id);
};

void run_diagnostics() {
}
""",
        "expected_symbols": [
            ("ThreadPool", "class", None),
            ("run_diagnostics", "function", None),
        ],
        "expected_imports": ["iostream", "vector"],
    },
    "PHP": {
        "code": b"""<?php
namespace Orchestrix\\Services;

use Psr\\Log\\LoggerInterface;

interface TaskContract {
    public function handle(): void;
}

class PipelineService implements TaskContract {
    public function handle(): void {
        echo "Processing";
    }
}
""",
        "expected_symbols": [
            ("Orchestrix\\Services", "namespace", None),
            ("TaskContract", "interface", None),
            ("PipelineService", "class", None),
            ("handle", "method", "PipelineService"),
        ],
        "expected_imports": ["Psr\\Log\\LoggerInterface"],
    },
    "C#": {
        "code": b"""using System;
using System.Threading.Tasks;

namespace Orchestrix.Core
{
    public interface IWorker
    {
        Task ExecuteAsync();
    }

    public class Worker : IWorker
    {
        public async Task ExecuteAsync()
        {
            await Task.Yield();
        }
    }
}
""",
        "expected_symbols": [
            ("Orchestrix.Core", "namespace", None),
            ("IWorker", "interface", None),
            ("Worker", "class", None),
            ("ExecuteAsync", "method", "Worker"),
        ],
        "expected_imports": ["System", "System.Threading.Tasks"],
    },
    "Go": {
        "code": b"""package main

import "sync"

type JobQueue struct {
    mu sync.Mutex
}

func (q *JobQueue) Push(job string) {
}

func NewQueue() *JobQueue {
    return &JobQueue{}
}
""",
        "expected_symbols": [
            ("JobQueue", "struct", None),
            ("Push", "method", "JobQueue"),
            ("NewQueue", "function", None),
        ],
        "expected_imports": ["sync"],
    },
    "Rust": {
        "code": b"""use std::sync::Arc;

pub trait Dispatcher {
    fn dispatch(&self, id: u64);
}

pub struct TaskHub {
    id: Arc<String>,
}

impl TaskHub {
    pub fn new(id: String) -> Self {
        Self { id: Arc::new(id) }
    }
}
""",
        "expected_symbols": [
            ("Dispatcher", "trait", None),
            ("TaskHub", "struct", None),
            ("new", "method", "TaskHub"),
        ],
        "expected_imports": ["std::sync::Arc"],
    },
    "Ruby": {
        "code": b"""require 'json'
require_relative 'config'

module Engine
  class Worker
    def perform(task)
      puts task
    end
  end
end
""",
        "expected_symbols": [
            ("Engine", "module", None),
            ("Worker", "class", "Engine"),
            ("perform", "method", "Worker"),
        ],
        "expected_imports": ["json", "config"],
    },
    "Swift": {
        "code": b"""import Foundation

public protocol ServiceDelegate: AnyObject {
    func didComplete()
}

public class NetworkService {
    public func fetch() {
    }
}
""",
        "expected_symbols": [
            ("ServiceDelegate", "interface", None),
            ("NetworkService", "class", None),
            ("fetch", "method", "NetworkService"),
        ],
        "expected_imports": ["Foundation"],
    },
    "Kotlin": {
        "code": b"""package com.orchestrix.demo
import java.util.List

class UserService(val id: String) {
    fun findUser(): String {
        return id
    }
}

interface UserRepository {
    fun getById(): String
}

fun topLevelUtility() = 42
""",
        "expected_symbols": [
            ("UserService", "class", None),
            ("findUser", "method", "UserService"),
            ("UserRepository", "interface", None),
            ("topLevelUtility", "function", None),
        ],
        "expected_imports": ["java.util.List"],
    },
    "Dart": {
        "code": b"""import 'dart:async';

class ApiClient {
    Future<String> send() async => "ok";
}

mixin LoggerMixin {
    void log(String s) => print(s);
}

enum Status { active, paused }
""",
        "expected_symbols": [
            ("ApiClient", "class", None),
            ("send", "method", "ApiClient"),
            ("LoggerMixin", "interface", None),
            ("Status", "enum", None),
        ],
        "expected_imports": ["dart:async"],
    },
    "Scala": {
        "code": b"""package com.orchestrix

import scala.concurrent.Future

trait Processor {
    def process(data: String): String
}

class Engine extends Processor {
    def process(data: String): String = data
}
""",
        "expected_symbols": [
            ("Processor", "interface", None),
            ("Engine", "class", None),
            ("process", "method", "Engine"),
        ],
        "expected_imports": ["scala.concurrent.Future"],
    },
    "Elixir": {
        "code": b"""defmodule Orchestrix.Queue do
  use GenServer
  import Logger

  def enqueue(item) do
    item
  end

  defp handle_internal(state) do
    state
  end
end
""",
        "expected_symbols": [
            ("Orchestrix.Queue", "module", None),
            ("enqueue", "method", "Orchestrix.Queue"),
            ("handle_internal", "method", "Orchestrix.Queue"),
        ],
        "expected_imports": ["GenServer", "Logger"],
    },
    "Haskell": {
        "code": b"""module Core where

import Data.List (sort)

data Config = Config String Int

class Worker a where
    work :: a -> IO ()

processData :: [Int] -> [Int]
processData xs = sort xs
""",
        "expected_symbols": [
            ("Core", "module", None),
            ("Config", "struct", None),
            ("Worker", "interface", None),
            ("processData", "function", None),
        ],
        "expected_imports": ["Data.List"],
    },
    "Solidity": {
        "code": b"""// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./IERC20.sol";

interface IReceiver {
    function onReceive() external;
}

contract Vault {
    struct Balance { uint256 amt; }
    enum State { Active, Inactive }

    function deposit() external payable {}
}
""",
        "expected_symbols": [
            ("IReceiver", "interface", None),
            ("Vault", "class", None),
            ("deposit", "method", "Vault"),
            ("Balance", "struct", "Vault"),
            ("State", "enum", "Vault"),
        ],
        "expected_imports": ["./IERC20.sol"],
    },
    "Lua": {
        "code": b"""local json = require("cjson")

local M = {}

function M.init(name)
    return { name = name }
end

function M:run()
    return true
end

return M
""",
        "expected_symbols": [
            ("M.init", "function", None),
            ("M:run", "method", None),
        ],
        "expected_imports": ["cjson"],
    },
    "Bash": {
        "code": b"""#!/usr/bin/env bash
source ./common.sh

function start_pipeline() {
    echo "Starting"
}

stop_pipeline() {
    echo "Stopping"
}
""",
        "expected_symbols": [
            ("start_pipeline", "function", None),
            ("stop_pipeline", "function", None),
        ],
        "expected_imports": ["./common.sh"],
    },
    "PowerShell": {
        "code": b"""using namespace System.Collections
Import-Module Az.Accounts

function Start-Cluster {
    param([string]$Name)
}

class JobScheduler {
    [void] Schedule() {}
}
""",
        "expected_symbols": [
            ("Start-Cluster", "function", None),
            ("JobScheduler", "class", None),
            ("Schedule", "method", "JobScheduler"),
        ],
        "expected_imports": ["System.Collections", "Az.Accounts"],
    },
    "SQL": {
        "code": b"""CREATE TABLE accounts (
    id UUID PRIMARY KEY,
    username VARCHAR(100) NOT NULL
);

CREATE VIEW active_accounts AS
SELECT id, username FROM accounts;

CREATE FUNCTION calculate_balance(user_id UUID) RETURNS NUMERIC AS $$
BEGIN
    RETURN 100;
END;
$$ LANGUAGE plpgsql;
""",
        "expected_symbols": [
            ("accounts", "struct", None),
            ("active_accounts", "struct", None),
            ("calculate_balance", "function", None),
        ],
        "expected_imports": [],
    },
    "Julia": {
        "code": b"""module AnalyticsEngine

using Statistics
import JSON

struct EngineConfig
    threads::Int
end

function calculate_mean(values::Vector{Float64})::Float64
    return mean(values)
end

macro timed_run(ex)
    quote $(esc(ex)) end
end

end
""",
        "expected_symbols": [
            ("AnalyticsEngine", "module", None),
            ("EngineConfig", "struct", "AnalyticsEngine"),
            ("calculate_mean", "function", "AnalyticsEngine"),
        ],
        "expected_imports": ["Statistics", "JSON"],
    },
    "Zig": {
        "code": b"""const std = @import("std");

pub const Config = struct {
    port: u16,
};

pub const ServerMode = enum {
    Production,
    Development,
};

pub fn run(cfg: Config) !void {
}

test "basic functionality" {
    try std.testing.expect(true);
}
""",
        "expected_symbols": [
            ("Config", "struct", None),
            ("ServerMode", "enum", None),
            ("run", "function", None),
            ("basic functionality", "function", None),
        ],
        "expected_imports": ["std"],
    },
    "OCaml": {
        "code": b"""open Stdlib

module Storage = struct
  type config = { max_size : int }
  let init () = ()
end

type result = Success | Failure
let execute () = ()
""",
        "expected_symbols": [
            ("Storage", "module", None),
            ("execute", "function", None),
        ],
        "expected_imports": ["Stdlib"],
    },
    "Perl": {
        "code": b"""package Orchestrix::Agent;
use strict;
use JSON::XS;

sub handle_event {
    my ($self, $event) = @_;
    return 1;
}

1;
""",
        "expected_symbols": [
            ("Orchestrix::Agent", "module", None),
            ("handle_event", "function", None),
        ],
        "expected_imports": ["JSON::XS"],
    },
    "Groovy": {
        "code": b"""package com.orchestrix.groovy;

import java.time.Instant;

class DeploymentScript {
    String environment;

    void deploy() {
        println("Deploying");
    }
}
""",
        "expected_symbols": [
            ("DeploymentScript", "class", None),
            ("deploy", "method", "DeploymentScript"),
        ],
        "expected_imports": ["java.time.Instant"],
    },
    "Fortran": {
        "code": b"""MODULE linear_solver
    IMPLICIT NONE
CONTAINS
    SUBROUTINE solve_system(a, b)
    END SUBROUTINE solve_system

    REAL FUNCTION compute_residual(r)
    END FUNCTION compute_residual
END MODULE linear_solver
""",
        "expected_symbols": [
            ("linear_solver", "module", None),
            ("solve_system", "method", "linear_solver"),
            ("compute_residual", "method", "linear_solver"),
        ],
        "expected_imports": [],
    },
    "Pascal": {
        "code": b"""unit CalcEngine;
interface
type
    TVector = record
        X, Y: Double;
    end;
function ComputeSum(A, B: Double): Double;
implementation
end.
""",
        "expected_symbols": [
            ("CalcEngine", "module", None),
            ("TVector", "struct", None),
            ("ComputeSum", "function", None),
        ],
        "expected_imports": [],
    },
    "CMake": {
        "code": b"""find_package(OpenSSL REQUIRED)
include(CTest)

function(setup_project project_name)
    message(STATUS "Configuring ${project_name}")
endfunction()

add_library(core_lib STATIC src/core.cpp)
add_executable(app_cli src/main.cpp)
""",
        "expected_symbols": [
            ("setup_project", "function", None),
            ("core_lib", "struct", None),
            ("app_cli", "struct", None),
        ],
        "expected_imports": ["OpenSSL", "CTest"],
    },
    "Make": {
        "code": b"""include common.mk

all: build test

build:
\t$(CC) -o app main.c

clean:
\trm -f app
""",
        "expected_symbols": [
            ("all", "function", None),
            ("build", "function", None),
            ("clean", "function", None),
        ],
        "expected_imports": ["common.mk"],
    },
    "HTML": {
        "code": b"""<!DOCTYPE html>
<html>
<head>
    <link rel="stylesheet" href="main.css">
    <script src="bundle.js"></script>
</head>
<body>
    <header id="site-header">Title</header>
    <main id="main-content">Body</main>
</body>
</html>
""",
        "expected_symbols": [
            ("#site-header", "struct", None),
            ("#main-content", "struct", None),
        ],
        "expected_imports": ["main.css", "bundle.js"],
    },
    "CSS": {
        "code": b"""@import url("variables.css");

.navbar-container {
    display: flex;
}

@keyframes slideDown {
    from { opacity: 0; }
    to { opacity: 1; }
}
""",
        "expected_symbols": [
            (".navbar-container", "struct", None),
            ("slideDown", "function", None),
        ],
        "expected_imports": ["variables.css"],
    },
    "XML": {
        "code": b"""<?xml version="1.0" encoding="UTF-8"?>
<project id="orchestrix-root" xmlns="http://maven.apache.org/POM/4.0.0">
    <configuration id="build-config">
        <property name="version">1.0.0</property>
    </configuration>
</project>
""",
        "expected_symbols": [
            ("#orchestrix-root", "struct", None),
            ("#build-config", "struct", None),
        ],
        "expected_imports": [],
    },
    "Markdown": {
        "code": b"""# Orchestrix Architecture

## Overview
Autonomous engineering platform.

### Code Intelligence
Tree-sitter parser registry.
""",
        "expected_symbols": [
            ("Orchestrix Architecture", "struct", None),
            ("Overview", "struct", None),
            ("Code Intelligence", "struct", None),
        ],
        "expected_imports": [],
    },
    "TOML": {
        "code": b"""[package]
name = "orchestrix"
version = "0.1.0"

[dependencies]
tokio = "1.0"
""",
        "expected_symbols": [
            ("package", "struct", None),
            ("dependencies", "struct", None),
        ],
        "expected_imports": [],
    },
    "JSON": {
        "code": b"""{
  "name": "orchestrix",
  "version": "1.0.0",
  "main": "index.js"
}
""",
        "expected_symbols": [
            ("name", "struct", None),
            ("version", "struct", None),
            ("main", "struct", None),
        ],
        "expected_imports": [],
    },
    "YAML": {
        "code": b"""name: CI
jobs:
  build:
    runs-on: ubuntu-latest
""",
        "expected_symbols": [
            ("name", "struct", None),
            ("jobs", "struct", None),
        ],
        "expected_imports": [],
    },
    "Objective-C": {
        "code": b"""#include <Foundation/Foundation.h>

struct Vector3 {
    float x, y, z;
};

int calculate_offset(struct Vector3 *v) {
    return 0;
}
""",
        "expected_symbols": [
            ("Vector3", "struct", None),
            ("calculate_offset", "function", None),
        ],
        "expected_imports": ["Foundation/Foundation.h"],
    },
}


# -----------------------------------------------------------------------------
# 2. Automated Extraction Accuracy Tests for Every Registered Language
# -----------------------------------------------------------------------------


@pytest.mark.parametrize("language", list(LANGUAGE_ACCURACY_FIXTURES.keys()))
def test_language_accuracy_fixture_extraction(language: str) -> None:
    """Validate that every registered language extracts symbols with correct names, types, and locations."""
    fixture = LANGUAGE_ACCURACY_FIXTURES[language]
    code = cast(bytes, fixture["code"])
    expected_symbols = cast(list[tuple[str, str, str | None]], fixture["expected_symbols"])
    expected_imports = cast(list[str], fixture["expected_imports"])

    intel = analyze_code_content(code, language)
    assert intel.line_count > 0, f"{language}: line_count should be > 0"
    assert intel.parse_error is None, f"{language}: unexpected parse error: {intel.parse_error}"

    # Verify expected symbols exist and have valid types and line coordinates
    for exp_name, exp_type, exp_parent in expected_symbols:
        matching_symbols = [
            s
            for s in intel.symbols
            if s.name == exp_name
            and s.symbol_type == exp_type
            and (exp_parent is None or s.parent_symbol_name == exp_parent)
        ]
        assert len(matching_symbols) > 0, (
            f"{language}: Missing expected symbol '{exp_name}' with type '{exp_type}' and parent '{exp_parent}'. "
            f"Extracted symbols: {[(s.name, s.symbol_type, s.parent_symbol_name) for s in intel.symbols]}"
        )
        sym = matching_symbols[0]
        assert sym.start_line >= 1, f"{language}: start_line must be >= 1"
        assert sym.end_line >= sym.start_line, f"{language}: end_line must be >= start_line"
        assert sym.start_column >= 0, f"{language}: start_column must be >= 0"
        assert sym.end_column >= sym.start_column, f"{language}: end_column must be >= start_column"
        assert sym.signature is not None and len(sym.signature) > 0, (
            f"{language}: signature should be populated"
        )
        if exp_parent:
            assert sym.parent_symbol_name == exp_parent, (
                f"{language}: Symbol '{exp_name}' expected parent '{exp_parent}', got '{sym.parent_symbol_name}'"
            )

    # Verify expected imports
    actual_imports = [i.module_name for i in intel.imports]
    for exp_imp in expected_imports:
        assert any(exp_imp in actual_imp for actual_imp in actual_imports), (
            f"{language}: Missing expected import '{exp_imp}'. Got: {actual_imports}"
        )


# -----------------------------------------------------------------------------
# 3. Edge Cases & Guardrail Tests
# -----------------------------------------------------------------------------


def test_empty_source_code_across_languages() -> None:
    """Empty files must produce 0 lines, 0 symbols, 0 imports, and no errors."""
    for lang in ("Python", "TypeScript", "Go", "Rust", "Java", "SQL", "HTML"):
        intel = analyze_code_content(b"", lang)
        assert intel.line_count == 0
        assert len(intel.symbols) == 0
        assert len(intel.imports) == 0
        assert intel.parse_error is None


def test_malformed_syntax_graceful_recovery() -> None:
    """Malformed syntax should be handled gracefully, extracting partial AST without crashing."""
    malformed_python = b"""def broken_function(
class AlsoBroken
"""
    intel = analyze_code_content(malformed_python, "Python")
    assert intel.line_count == 2
    # Recoverable syntax flag set
    assert intel.parse_error is not None
    assert "recoverable" in intel.parse_error.lower()


def test_large_file_parsing_safety() -> None:
    """Parser must handle moderately large source files (e.g. 500 lines) within memory limits."""
    lines = [b"def func_%d(x: int) -> int:\n    return x + %d\n" % (i, i) for i in range(250)]
    large_py = b"\n".join(lines)
    intel = analyze_code_content(large_py, "Python")
    assert intel.line_count >= 500
    assert len(intel.symbols) == 250
    assert intel.symbols[0].name == "func_0"
    assert intel.symbols[249].name == "func_249"


def test_unicode_identifiers_support() -> None:
    """Unicode identifiers should be preserved and extracted accurately where supported."""
    code = b"""class \xce\xa3\xcf\x85\xce\xbd\xce\xac\xcf\x81\xcf\x84\xce\xb7\xcf\x83\xce\xb7:
    def \xcf\x80\xcf\x81\xce\xac\xce\xbe\xce\xb7(self):
        pass
"""
    intel = analyze_code_content(code, "Python")
    assert len(intel.symbols) >= 2
    names = [s.name for s in intel.symbols]
    assert "\u03a3\u03c5\u03bd\u03ac\u03c1\u03c4\u03b7\u03c3\u03b7" in names


def test_duplicate_symbol_prevention() -> None:
    """De-duplication helper must reject identical symbols at the same coordinates."""
    code = b"""class Alpha {
    execute() {}
}
"""
    intel = analyze_code_content(code, "JavaScript")
    names = [s.name for s in intel.symbols]
    assert names.count("Alpha") == 1
    assert names.count("execute") == 1


def test_unregistered_language_fallback() -> None:
    """Unknown or unregistered language names must return graceful fallback without raising exceptions."""
    intel = analyze_code_content(b"print('hello')", "Brainfuck")
    assert intel.language == "Brainfuck"
    assert len(intel.symbols) == 0
    assert len(intel.imports) == 0
    assert intel.parse_error is None


def test_all_registered_languages_have_active_parsers() -> None:
    """Verify that every single registered language has an active parser."""
    langs = PARSER_REGISTRY.get_supported_languages()
    assert len(langs) >= 40
    for lang in langs:
        parser = PARSER_REGISTRY.get_parser(lang)
        assert parser is not None, f"Parser for {lang} should be active and non-None"
        spec = PARSER_REGISTRY.get_language_spec(lang)
        assert spec is not None
        assert spec.extraction_mode in ("validated", "generic")
