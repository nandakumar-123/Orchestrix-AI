# SecureFlow Architecture & Pipeline

## Overview

**SecureFlow** is Orchestrix AI's autonomous application security analysis agent. It conducts multi-vector vulnerability scanning across repository source code, dependencies, and environment configurations.

## Core Capabilities

1. **Secret & Credential Detection**: High-precision regex pattern scanning combined with Shannon entropy analysis to identify leaked API tokens, private keys, database URLs, and bearer tokens.
2. **Dependency Vulnerability Scanning**: Integration with `pip-audit` for Python and `npm audit` for Node.js ecosystems, cross-referenced with OSV advisories.
3. **Static Application Security Testing (SAST)**: Semgrep integration targeting OWASP Top 10 vulnerabilities (SQLi, XSS, Path Traversal, Command Injection, Insecure Deserialization).
4. **Repository-Scoped Deduplication**: Deterministic SHA-256 fingerprinting ensures persistent tracking and prevents duplicate findings across recurrent scans.
5. **Partial Completion Handling**: Scans where one or more scanners are unavailable or fail transition to `PARTIALLY_COMPLETED` with explicit scanner metadata, never silently passing or masquerading as clean.
6. **DevPilot Remediation Bridge**: Safe internal conversion of security findings into DevPilot remediation tasks with scrubbed prompts and preserved human approval gates.

## Scanning Pipeline

```
+---------------------------------------------------------------------------------+
|                                SecureFlowService                                |
+---------------------------------------------------------------------------------+
       |                              |                               |
       v                              v                               v
+------------------+        +--------------------+        +-----------------------+
|  SecretScanner   |        | DependencyScanner  |        |      SASTScanner      |
|  (Regex+Entropy) |        | (pip-audit/npm/OSV)|        |       (Semgrep)       |
+------------------+        +--------------------+        +-----------------------+
       |                              |                               |
       +------------------------------+-------------------------------+
                                      |
                                      v
                          +-----------------------+
                          |     FindingManager    |
                          | (SHA-256 Fingerprint) |
                          +-----------------------+
                                      |
                                      v
                          +-----------------------+
                          |   SecureFlowFinding   |
                          |   SecureFlowScanEvent |
                          +-----------------------+
                                      |
                                      v
                          +-----------------------+
                          |   RemediationBridge   |
                          |     -> DevPilot       |
                          +-----------------------+
```
