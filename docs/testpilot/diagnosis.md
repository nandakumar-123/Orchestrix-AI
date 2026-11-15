# TestPilot Test Failure Diagnosis

## Overview

The `FailureDiagnoser` (`app.services.testpilot.diagnoser`) provides automated post-mortem root-cause analysis and remediation suggestions when test suites fail.

## Diagnostic Workflow

1. **Structured Traceback Parsing**:
   - Extracts failing test names, error types, error messages, and file/line stack frames for Python (`Traceback (most recent call last)`) and JavaScript/TypeScript (`at Function (file:line:col)`).
2. **Pre-LLM Secret Redaction**:
   - Uses `redact_secrets` to scrub all API keys, access tokens, passwords, and private keys from raw logs and source code context before LLM prompt assembly.
3. **Root-Cause Analysis**:
   - Queries LLM provider to explain why the test failed and identify the exact faulty logic or invariant violation.
4. **Actionable Fix Suggestions**:
   - Synthesizes 2 to 4 concrete, idiomatic code remediation suggestions with confidence scores.
5. **Non-Mutating Policy**:
   - The failure diagnoser strictly provides advisory output. It never modifies files, commits changes, or bypasses test assertions automatically.
