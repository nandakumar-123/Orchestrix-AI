# TestPilot Controlled Test Execution

## Overview

The `TestPilotRunner` (`app.services.testpilot.runner`) manages sandboxed execution of approved test suites using the Phase 11 `ControlledTestRunner` infrastructure.

## Security Constraints & Isolation

1. **Mandatory Approval Verification**: The runner verifies that `suite.status == TestSuiteStatus.APPROVED`. Unapproved suites immediately raise `TestApprovalRequiredError`.
2. **Command Allowlist**: Only sanctioned test runners (`pytest`, `python -m pytest`, `npm test`, `npx vitest`, `npx jest`) are permitted. Any command attempting shell chaining (`&&`, `||`, `;`, `|`), subshells, or unauthorized binaries raises `TestExecutionSecurityError`.
3. **Process Sandboxing**:
   - Windows: Bound to a `Windows Job Object` with kill-on-job-close semantics to prevent lingering worker processes.
   - Resource limits: Dedicated memory limits (default 2GB) and wall-clock timeout bounds (default 120s).
4. **Isolated Workspaces**: Tests run against clean task workspaces or isolated temporary clones created by `TaskWorkspaceManager`.
5. **Output Normalization**: Execution output (exit codes, stdout, stderr, execution duration) is parsed to extract individual test case results and persisted to `TestPilotExecution` and `TestPilotCaseResult` tables.
